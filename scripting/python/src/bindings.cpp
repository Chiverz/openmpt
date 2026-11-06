/*
 * bindings.cpp
 * ------------
 * Purpose: pybind11 bindings exposing OpenMPT's CSoundFile to Python for
 *          headless, script-driven module composition (mptscript._core).
 * Notes  : This is deliberately a thin layer. Friendly APIs live in the
 *          pure-Python `mptscript` package.
 * Authors: OpenMPT Devs / mptscript contributors
 * The OpenMPT source code is released under the BSD license. Read LICENSE for more details.
 */

#include "openmpt/all/BuildSettings.hpp"

#include "common/stdafx.h"

#include "mpt/audio/span.hpp"
#include "mpt/io_read/filecursor_memory.hpp"

#include "common/FileReader.h"
#include "common/Logging.h"
#include "common/mptRandom.h"
#include "soundlib/AudioReadTarget.h"
#include "soundlib/Message.h"
#include "soundlib/ModSequence.h"
#include "soundlib/Sndfile.h"
#include "soundlib/mod_specifications.h"
#include "soundlib/modcommand.h"
#include "soundlib/plugins/PlugInterface.h"
#include "soundlib/plugins/PluginManager.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <algorithm>
#include <cstdio>
#include <cmath>
#include <memory>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace py = pybind11;

OPENMPT_NAMESPACE_BEGIN

#if defined(MPT_ASSERT_HANDLER_NEEDED)
// The engine expects the host (libopenmpt, the tracker, ...) to provide this.
MPT_ATTR_NOINLINE MPT_DECL_NOINLINE void AssertHandler(const mpt::source_location &loc, const char *expr, const char *msg)
{
	std::fprintf(stderr, "mptscript: engine assertion failed: %s%s%s (%s:%u)\n", expr, msg ? " - " : "", msg ? msg : "", loc.file_name(), static_cast<unsigned>(loc.line()));
}
#endif

namespace
{

struct FormatInfo
{
	const char *name;
	MODTYPE type;
};

constexpr FormatInfo kFormats[] = {
	{"it", MOD_TYPE_IT},
	{"mptm", MOD_TYPE_MPT},
	{"xm", MOD_TYPE_XM},
	{"s3m", MOD_TYPE_S3M},
	{"mod", MOD_TYPE_MOD},
};

MODTYPE ParseFormat(const std::string &name)
{
	for(const auto &f : kFormats)
		if(name == f.name)
			return f.type;
	throw py::value_error("unknown module format '" + name + "' (expected it, mptm, xm, s3m or mod)");
}

std::string FormatName(MODTYPE type)
{
	for(const auto &f : kFormats)
		if(type == f.type)
			return f.name;
	return "other";
}

int OrderToPy(PATTERNINDEX pat)
{
	if(pat == PATTERNINDEX_INVALID)
		return -1;
	if(pat == PATTERNINDEX_SKIP)
		return -2;
	return pat;
}

PATTERNINDEX OrderFromPy(int pat)
{
	if(pat == -1)
		return PATTERNINDEX_INVALID;
	if(pat == -2)
		return PATTERNINDEX_SKIP;
	if(pat < 0 || pat >= MAX_PATTERNS)
		throw py::value_error("order list entry out of range: " + std::to_string(pat));
	return static_cast<PATTERNINDEX>(pat);
}

template <typename T>
T GetOr(const py::dict &d, const char *key, T def)
{
	if(d.contains(key))
		return d[key].cast<T>();
	return def;
}

py::dict EnvelopeToPy(const InstrumentEnvelope &env)
{
	py::dict d;
	py::list points;
	for(const auto &node : env)
		points.append(py::make_tuple(node.tick, node.value));
	d["points"] = points;
	d["enabled"] = env.dwFlags[ENV_ENABLED];
	d["carry"] = env.dwFlags[ENV_CARRY];
	d["filter"] = env.dwFlags[ENV_FILTER];
	if(env.dwFlags[ENV_LOOP])
		d["loop"] = py::make_tuple(env.nLoopStart, env.nLoopEnd);
	else
		d["loop"] = py::none();
	if(env.dwFlags[ENV_SUSTAIN])
		d["sustain"] = py::make_tuple(env.nSustainStart, env.nSustainEnd);
	else
		d["sustain"] = py::none();
	return d;
}

void EnvelopeFromPy(InstrumentEnvelope &env, const py::dict &d)
{
	if(d.contains("points"))
	{
		env.clear();
		for(auto item : d["points"])
		{
			auto pt = item.cast<std::pair<int, int>>();
			env.push_back(static_cast<EnvelopeNode::tick_t>(std::clamp(pt.first, 0, 0xFFFF)), static_cast<EnvelopeNode::value_t>(std::clamp(pt.second, 0, int(ENVELOPE_MAX))));
		}
	}
	if(d.contains("enabled"))
		env.dwFlags.set(ENV_ENABLED, d["enabled"].cast<bool>());
	if(d.contains("carry"))
		env.dwFlags.set(ENV_CARRY, d["carry"].cast<bool>());
	if(d.contains("filter"))
		env.dwFlags.set(ENV_FILTER, d["filter"].cast<bool>());
	if(d.contains("loop"))
	{
		if(d["loop"].is_none())
		{
			env.dwFlags.reset(ENV_LOOP);
		} else
		{
			auto lp = d["loop"].cast<std::pair<int, int>>();
			env.nLoopStart = static_cast<uint8>(lp.first);
			env.nLoopEnd = static_cast<uint8>(lp.second);
			env.dwFlags.set(ENV_LOOP);
		}
	}
	if(d.contains("sustain"))
	{
		if(d["sustain"].is_none())
		{
			env.dwFlags.reset(ENV_SUSTAIN);
		} else
		{
			auto sp = d["sustain"].cast<std::pair<int, int>>();
			env.nSustainStart = static_cast<uint8>(sp.first);
			env.nSustainEnd = static_cast<uint8>(sp.second);
			env.dwFlags.set(ENV_SUSTAIN);
		}
	}
	env.Sanitize();
}


// Collects the engine's log messages (loader/saver warnings) instead of printing them to stderr.
class LogCollector final : public ILog
{
public:
	mutable std::vector<std::pair<int, std::string>> messages;
	void AddToLog(LogLevel level, const mpt::ustring &text) const override
	{
		messages.emplace_back(static_cast<int>(level), mpt::ToCharset(mpt::Charset::UTF8, text));
	}
};


class Module
{
public:
	std::unique_ptr<LogCollector> log;
	std::unique_ptr<CSoundFile> snd;

	Module()
		: log(std::make_unique<LogCollector>())
		, snd(std::make_unique<CSoundFile>())
	{
		snd->SetCustomLog(log.get());
	}

	~Module()
	{
		snd.reset();  // destroy the sound file before the log it points to
	}

	py::list TakeMessages()
	{
		py::list out;
		for(const auto &[level, text] : log->messages)
		{
			const char *name = level <= LogError ? "error" : level == LogWarning ? "warning" : level == LogNotification ? "notification" : "info";
			out.append(py::make_tuple(name, text));
		}
		log->messages.clear();
		return out;
	}

	// --- Construction -------------------------------------------------------

	static std::unique_ptr<Module> New(const std::string &format, int channels)
	{
		const MODTYPE type = ParseFormat(format);
		const auto &specs = CSoundFile::GetModSpecifications(type);
		if(channels < 1 || channels > specs.channelsMax)
			throw py::value_error("format '" + format + "' supports 1.." + std::to_string(specs.channelsMax) + " channels");

		auto m = std::make_unique<Module>();
		CSoundFile &s = *m->snd;
		// Mirrors CModDoc::InitializeMod() in the tracker.
		s.Create(type, static_cast<CHANNELINDEX>(channels));
		s.m_SongFlags.set(SONG_LINEARSLIDES & s.GetModSpecifications().songFlags);
		if(type == MOD_TYPE_MPT)
		{
			s.m_nTempoMode = TempoMode::Modern;
			s.m_SongFlags.set(SONG_EXFILTERRANGE);
		}
		s.SetDefaultPlaybackBehaviour(type);
		s.SetMixLevels(s.GetModSpecifications().defaultMixLevels);
		s.Order().assign(1, 0);
		if(!s.Patterns.IsValidPat(0))
			s.Patterns.Insert(0, 64);
		s.Order().SetDefaultTempoInt(125);
		s.Order().SetDefaultSpeed(6);
		s.m_PlayState.m_nGlobalVolume = s.m_nDefaultGlobalVolume = MAX_GLOBAL_VOLUME;
		s.m_nSamplePreAmp = s.m_nVSTiVolume = 48;
		s.m_nDefaultRowsPerBeat = 4;
		s.m_nDefaultRowsPerMeasure = 16;
		s.SetupMODPanning(type == MOD_TYPE_MOD);
		if(type == MOD_TYPE_MOD)
		{
			s.m_SongFlags.set(SONG_ISAMIGA | SONG_AMIGALIMITS | SONG_PT_MODE);
			s.m_SongFlags.set(SONG_FORMAT_NO_VOLCOL);
			s.m_playBehaviour.set(kMODOneShotLoops);
			s.m_playBehaviour.set(kMODSampleSwap);
			s.m_playBehaviour.set(kMODOutOfRangeNoteDelay);
			s.m_playBehaviour.set(kMODTempoOnSecondTick);
			s.m_playBehaviour.set(kFT2MODTremoloRampWaveform);
		}
		s.m_nSamples = 0;
		s.ResetPlayPos();
		return m;
	}

	static std::unique_ptr<Module> Load(const py::bytes &data)
	{
		std::string buf = data;
		auto m = std::make_unique<Module>();
		FileReader file = mpt::IO::make_FileCursor<mpt::PathString>(mpt::as_span(reinterpret_cast<const std::byte *>(buf.data()), buf.size()));
		if(!m->snd->Create(file, CSoundFile::loadCompleteModule))
			throw py::value_error("could not load module: unrecognised or corrupt file");
		m->snd->Order.SetSequence(0);
		return m;
	}

	// Saves to a file (the S3M writer seeks past the end of the stream, which
	// only real files support, so there is no in-memory variant).
	void Save(const std::string &utf8Path, const std::string &format) const
	{
		CSoundFile &s = *snd;
		const MODTYPE target = format.empty() ? s.GetBestSaveFormat() : ParseFormat(format);
		const MODTYPE best = s.GetBestSaveFormat();
		if(target != best)
			throw py::value_error("this module is a '" + FormatName(best) + "' module and can only be saved as that format (format conversion is a tracker-GUI feature)");
		const std::filesystem::path path(std::u8string(reinterpret_cast<const char8_t *>(utf8Path.data()), utf8Path.size()));
		std::ofstream f(path, std::ios::out | std::ios::binary | std::ios::trunc);
		if(!f)
			throw std::runtime_error("could not open '" + utf8Path + "' for writing");
		bool ok = false;
		if(target == MOD_TYPE_IT || target == MOD_TYPE_MPT)
		{
			ok = s.SaveIT(f, mpt::PathString(), false);
		} else if(target == MOD_TYPE_XM)
		{
			ok = s.SaveXM(f, false);
		} else if(target == MOD_TYPE_S3M)
		{
			ok = s.SaveS3M(f);
		} else if(target == MOD_TYPE_MOD)
		{
			ok = s.SaveMod(f);
		}
		f.flush();
		if(!ok || !f)
			throw std::runtime_error("saving '" + utf8Path + "' failed");
	}

	// --- Song properties ----------------------------------------------------

	std::string GetFormat() const { return FormatName(snd->GetBestSaveFormat()); }
	std::string GetTitle() const { return snd->GetTitle(); }
	void SetTitle(const std::string &t) { snd->SetTitle(t); }
	std::string GetArtist() const { return mpt::ToCharset(mpt::Charset::UTF8, snd->m_songArtist); }
	void SetArtist(const std::string &a) { snd->m_songArtist = mpt::ToUnicode(mpt::Charset::UTF8, a); }
	// Song message with '\n' line breaks (formats store CR or CRLF internally).
	std::string GetMessage() const { return snd->m_songMessage.GetFormatted(SongMessage::leLF); }
	void SetMessage(const std::string &m) { snd->m_songMessage.SetFormatted(m, SongMessage::leLF); }

	int GetTempo() const { return snd->Order().GetDefaultTempo().GetInt(); }
	void SetTempo(int t)
	{
		const auto &specs = snd->GetModSpecifications();
		t = std::clamp(t, static_cast<int>(specs.GetTempoMin().GetInt()), static_cast<int>(specs.GetTempoMax().GetInt()));
		snd->Order().SetDefaultTempoInt(t);
	}
	int GetSpeed() const { return static_cast<int>(snd->Order().GetDefaultSpeed()); }
	void SetSpeed(int s)
	{
		const auto &specs = snd->GetModSpecifications();
		s = std::clamp(s, static_cast<int>(specs.speedMin), static_cast<int>(specs.speedMax));
		snd->Order().SetDefaultSpeed(s);
	}
	int GetGlobalVolume() const { return static_cast<int>(snd->m_nDefaultGlobalVolume); }
	void SetGlobalVolume(int v) { snd->m_nDefaultGlobalVolume = std::clamp(v, 0, int(MAX_GLOBAL_VOLUME)); }
	int GetSamplePreamp() const { return static_cast<int>(snd->m_nSamplePreAmp); }
	void SetSamplePreamp(int v) { snd->m_nSamplePreAmp = std::clamp(v, 1, 2000); }
	int GetRowsPerBeat() const { return static_cast<int>(snd->m_nDefaultRowsPerBeat); }
	void SetRowsPerBeat(int v) { snd->m_nDefaultRowsPerBeat = std::max(1, v); }
	int GetRowsPerMeasure() const { return static_cast<int>(snd->m_nDefaultRowsPerMeasure); }
	void SetRowsPerMeasure(int v) { snd->m_nDefaultRowsPerMeasure = std::max(1, v); }
	int GetRestartPos() const { return snd->Order().GetRestartPos(); }
	void SetRestartPos(int v) { snd->Order().SetRestartPos(static_cast<ORDERINDEX>(std::max(0, v))); }
	bool GetLinearSlides() const { return snd->m_SongFlags[SONG_LINEARSLIDES]; }
	void SetLinearSlides(bool v) { snd->m_SongFlags.set(SONG_LINEARSLIDES, v); }

	py::dict Limits() const
	{
		const auto &specs = snd->GetModSpecifications();
		py::dict d;
		d["channels_max"] = specs.channelsMax;
		d["channels_min"] = specs.channelsMin;
		d["patterns_max"] = specs.patternsMax;
		d["orders_max"] = specs.ordersMax;
		d["rows_min"] = specs.patternRowsMin;
		d["rows_max"] = specs.patternRowsMax;
		d["samples_max"] = specs.samplesMax;
		d["instruments_max"] = specs.instrumentsMax;
		d["tempo_min"] = specs.GetTempoMin().GetInt();
		d["tempo_max"] = specs.GetTempoMax().GetInt();
		d["speed_min"] = specs.speedMin;
		d["speed_max"] = specs.speedMax;
		d["has_volume_column"] = specs.HasVolCommand(VOLCMD_VOLUME);
		d["has_note_off"] = specs.hasNoteOff;
		d["has_note_cut"] = specs.hasNoteCut;
		d["has_comments"] = specs.hasComments;
		d["has_plugins"] = specs.supportsPlugins;
		d["has_opl"] = snd->SupportsOPL();
		d["has_instruments"] = specs.instrumentsMax > 0;
		d["note_min"] = specs.noteMin;
		d["note_max"] = specs.noteMax;
		return d;
	}

	// --- Channels -----------------------------------------------------------

	int NumChannels() const { return snd->GetNumChannels(); }

	void SetNumChannels(int newCount)
	{
		CSoundFile &s = *snd;
		const auto &specs = s.GetModSpecifications();
		if(newCount < std::max<int>(1, specs.channelsMin) || newCount > specs.channelsMax)
			throw py::value_error("channel count out of range for this format (max " + std::to_string(specs.channelsMax) + ")");
		const CHANNELINDEX oldCount = s.GetNumChannels();
		if(newCount == oldCount)
			return;
		// Re-layout every pattern (row-major, channel-interleaved storage).
		std::vector<std::pair<PATTERNINDEX, std::vector<ModCommand>>> saved;
		for(PATTERNINDEX p = 0; p < s.Patterns.Size(); p++)
		{
			if(!s.Patterns.IsValidPat(p))
				continue;
			const CPattern &pat = s.Patterns[p];
			const ROWINDEX rows = pat.GetNumRows();
			std::vector<ModCommand> data(static_cast<size_t>(rows) * newCount);
			for(ROWINDEX r = 0; r < rows; r++)
				for(CHANNELINDEX c = 0; c < std::min<CHANNELINDEX>(oldCount, static_cast<CHANNELINDEX>(newCount)); c++)
					data[static_cast<size_t>(r) * newCount + c] = *pat.GetpModCommand(r, c);
			saved.emplace_back(p, std::move(data));
		}
		s.ChnSettings.resize(static_cast<CHANNELINDEX>(newCount));
		for(auto &[p, data] : saved)
			s.Patterns[p].SetData(std::move(data));
		for(CHANNELINDEX c = oldCount; c < newCount; c++)
			s.m_PlayState.Chn[c].Reset(ModChannel::resetTotal, s, c, CSoundFile::GetChannelMuteFlag());
	}

	ModChannelSettings &Chn(int c)
	{
		if(c < 0 || c >= snd->GetNumChannels())
			throw py::index_error("channel index out of range");
		return snd->ChnSettings[c];
	}

	py::dict ChannelGet(int c)
	{
		const auto &cs = Chn(c);
		py::dict d;
		d["name"] = std::string(cs.szName);
		d["pan"] = cs.nPan;
		d["volume"] = cs.nVolume;
		d["mute"] = cs.dwFlags[CHN_MUTE];
		d["surround"] = cs.dwFlags[CHN_SURROUND];
		d["plugin"] = static_cast<int>(cs.nMixPlugin);
		return d;
	}

	void ChannelSet(int c, const py::dict &d)
	{
		auto &cs = Chn(c);
		if(d.contains("name"))
			cs.szName = d["name"].cast<std::string>();
		if(d.contains("pan"))
			cs.nPan = static_cast<uint16>(std::clamp(d["pan"].cast<int>(), 0, 256));
		if(d.contains("volume"))
			cs.nVolume = static_cast<uint8>(std::clamp(d["volume"].cast<int>(), 0, 64));
		if(d.contains("mute"))
			cs.dwFlags.set(CHN_MUTE, d["mute"].cast<bool>());
		if(d.contains("surround"))
			cs.dwFlags.set(CHN_SURROUND, d["surround"].cast<bool>());
		if(d.contains("plugin"))
		{
			const int plug = d["plugin"].cast<int>();
			if(plug < 0 || plug > int(MAX_MIXPLUGINS))
				throw py::value_error("plugin number must be 0 (none) or 1.." + std::to_string(MAX_MIXPLUGINS));
			cs.nMixPlugin = static_cast<PLUGINDEX>(plug);
		}
	}

	// --- Order list ---------------------------------------------------------

	std::vector<int> GetOrder() const
	{
		std::vector<int> out;
		for(PATTERNINDEX p : snd->Order())
			out.push_back(OrderToPy(p));
		return out;
	}

	void SetOrder(const std::vector<int> &order)
	{
		const auto &specs = snd->GetModSpecifications();
		if(order.size() > specs.ordersMax)
			throw py::value_error("order list too long for this format (max " + std::to_string(specs.ordersMax) + ")");
		auto &seq = snd->Order();
		seq.resize(0);
		for(int p : order)
			seq.push_back(OrderFromPy(p));
	}

	// --- Patterns -----------------------------------------------------------

	int NumPatterns() const { return snd->Patterns.Size(); }
	bool PatternExists(int p) const { return p >= 0 && snd->Patterns.IsValidPat(static_cast<PATTERNINDEX>(p)); }

	CPattern &Pat(int p)
	{
		if(!PatternExists(p))
			throw py::index_error("pattern " + std::to_string(p) + " does not exist");
		return snd->Patterns[p];
	}

	int PatternAdd(int rows, int index)
	{
		const auto &specs = snd->GetModSpecifications();
		if(rows < static_cast<int>(specs.patternRowsMin) || rows > static_cast<int>(specs.patternRowsMax))
			throw py::value_error("pattern rows must be in " + std::to_string(specs.patternRowsMin) + ".." + std::to_string(specs.patternRowsMax) + " for this format");
		if(index < 0)
		{
			PATTERNINDEX p = snd->Patterns.InsertAny(static_cast<ROWINDEX>(rows), true);
			if(p == PATTERNINDEX_INVALID)
				throw std::runtime_error("no free pattern slots left for this format");
			return p;
		}
		if(index >= static_cast<int>(specs.patternsMax))
			throw py::value_error("pattern index out of range for this format");
		if(snd->Patterns.IsValidPat(static_cast<PATTERNINDEX>(index)))
			throw py::value_error("pattern " + std::to_string(index) + " already exists");
		if(!snd->Patterns.Insert(static_cast<PATTERNINDEX>(index), static_cast<ROWINDEX>(rows)))
			throw std::runtime_error("could not create pattern");
		return index;
	}

	int PatternDuplicate(int p)
	{
		Pat(p);
		PATTERNINDEX n = snd->Patterns.Duplicate(static_cast<PATTERNINDEX>(p), true);
		if(n == PATTERNINDEX_INVALID)
			throw std::runtime_error("no free pattern slots left for this format");
		return n;
	}

	void PatternRemove(int p)
	{
		Pat(p);
		snd->Patterns.Remove(static_cast<PATTERNINDEX>(p));
	}

	int PatternRows(int p) { return Pat(p).GetNumRows(); }

	void PatternResize(int p, int rows)
	{
		if(!Pat(p).Resize(static_cast<ROWINDEX>(rows), true, true))
			throw py::value_error("could not resize pattern (row count out of range for this format?)");
	}

	std::string PatternGetName(int p) { return Pat(p).GetName(); }
	void PatternSetName(int p, const std::string &name) { Pat(p).SetName(name); }

	void PatternClear(int p) { Pat(p).ClearCommands(); }

	ModCommand &Cell(int p, int row, int chn)
	{
		CPattern &pat = Pat(p);
		if(row < 0 || row >= static_cast<int>(pat.GetNumRows()))
			throw py::index_error("row " + std::to_string(row) + " out of range (pattern has " + std::to_string(pat.GetNumRows()) + " rows)");
		if(chn < 0 || chn >= snd->GetNumChannels())
			throw py::index_error("channel " + std::to_string(chn) + " out of range (song has " + std::to_string(snd->GetNumChannels()) + " channels)");
		return *pat.GetpModCommand(static_cast<ROWINDEX>(row), static_cast<CHANNELINDEX>(chn));
	}

	py::tuple CellGet(int p, int row, int chn)
	{
		const ModCommand &m = Cell(p, row, chn);
		return py::make_tuple(m.note, m.instr, static_cast<int>(m.volcmd), m.vol, static_cast<int>(m.command), m.param);
	}

	void CellSet(int p, int row, int chn, int note, int instr, int volcmd, int vol, int command, int param)
	{
		ModCommand &m = Cell(p, row, chn);
		m.note = static_cast<ModCommand::NOTE>(std::clamp(note, 0, 255));
		m.instr = static_cast<ModCommand::INSTR>(std::clamp(instr, 0, 255));
		m.volcmd = static_cast<VolumeCommand>(std::clamp(volcmd, 0, int(MAX_VOLCMDS) - 1));
		m.vol = static_cast<ModCommand::VOL>(std::clamp(vol, 0, 255));
		m.command = static_cast<EffectCommand>(std::clamp(command, 0, int(MAX_EFFECTS) - 1));
		m.param = static_cast<ModCommand::PARAM>(std::clamp(param, 0, 255));
	}

	// Bulk access: bytes of rows*channels*6 in (note, instr, volcmd, vol, command, param) order.
	py::bytes PatternGetData(int p)
	{
		const CPattern &pat = Pat(p);
		const ROWINDEX rows = pat.GetNumRows();
		const CHANNELINDEX chns = snd->GetNumChannels();
		std::string out(static_cast<size_t>(rows) * chns * 6, '\0');
		size_t i = 0;
		for(ROWINDEX r = 0; r < rows; r++)
		{
			for(CHANNELINDEX c = 0; c < chns; c++)
			{
				const ModCommand &m = *pat.GetpModCommand(r, c);
				out[i++] = static_cast<char>(m.note);
				out[i++] = static_cast<char>(m.instr);
				out[i++] = static_cast<char>(m.volcmd);
				out[i++] = static_cast<char>(m.vol);
				out[i++] = static_cast<char>(m.command);
				out[i++] = static_cast<char>(m.param);
			}
		}
		return py::bytes(out);
	}

	void PatternSetData(int p, const py::bytes &data)
	{
		CPattern &pat = Pat(p);
		std::string buf = data;
		const ROWINDEX rows = pat.GetNumRows();
		const CHANNELINDEX chns = snd->GetNumChannels();
		if(buf.size() != static_cast<size_t>(rows) * chns * 6)
			throw py::value_error("pattern data size mismatch");
		size_t i = 0;
		for(ROWINDEX r = 0; r < rows; r++)
		{
			for(CHANNELINDEX c = 0; c < chns; c++)
			{
				ModCommand &m = *pat.GetpModCommand(r, c);
				m.note = static_cast<uint8>(buf[i++]);
				m.instr = static_cast<uint8>(buf[i++]);
				m.volcmd = static_cast<VolumeCommand>(std::min<uint8>(static_cast<uint8>(buf[i++]), MAX_VOLCMDS - 1));
				m.vol = static_cast<uint8>(buf[i++]);
				m.command = static_cast<EffectCommand>(std::min<uint8>(static_cast<uint8>(buf[i++]), MAX_EFFECTS - 1));
				m.param = static_cast<uint8>(buf[i++]);
			}
		}
	}

	std::string EffectLetter(int cmd) const
	{
		return std::string(1, snd->GetModSpecifications().GetEffectLetter(static_cast<ModCommand::COMMAND>(cmd)));
	}

	std::string VolEffectLetter(int volcmd) const
	{
		return std::string(1, snd->GetModSpecifications().GetVolEffectLetter(static_cast<ModCommand::VOLCMD>(volcmd)));
	}

	bool SupportsEffect(int cmd) const { return snd->GetModSpecifications().HasCommand(static_cast<ModCommand::COMMAND>(cmd)); }
	bool SupportsVolEffect(int volcmd) const { return snd->GetModSpecifications().HasVolCommand(static_cast<ModCommand::VOLCMD>(volcmd)); }

	// --- Samples ------------------------------------------------------------

	int NumSamples() const { return snd->GetNumSamples(); }

	ModSample &Smp(int i, bool create)
	{
		const auto &specs = snd->GetModSpecifications();
		if(i < 1 || i > static_cast<int>(specs.samplesMax))
			throw py::index_error("sample index must be 1.." + std::to_string(specs.samplesMax) + " for this format");
		if(i > snd->GetNumSamples())
		{
			if(!create)
				throw py::index_error("sample " + std::to_string(i) + " does not exist");
			for(int n = snd->GetNumSamples() + 1; n <= i; n++)
			{
				snd->m_nSamples = static_cast<SAMPLEINDEX>(n);
				snd->GetSample(static_cast<SAMPLEINDEX>(n)).Initialize(snd->GetType());
				snd->m_szNames[n] = "";
			}
		}
		return snd->GetSample(static_cast<SAMPLEINDEX>(i));
	}

	// data: float values in [-1, 1], interleaved if channels == 2.
	void SampleSetData(int i, const std::vector<float> &data, int channels, int bits)
	{
		if(channels != 1 && channels != 2)
			throw py::value_error("channels must be 1 or 2");
		if(bits != 8 && bits != 16)
			throw py::value_error("bits must be 8 or 16");
		if(data.size() % channels)
			throw py::value_error("interleaved data length must be a multiple of channels");
		ModSample &smp = Smp(i, true);
		const SmpLength frames = static_cast<SmpLength>(data.size() / channels);
		smp.FreeSample();
		smp.nLength = frames;
		smp.uFlags.set(CHN_16BIT, bits == 16);
		smp.uFlags.set(CHN_STEREO, channels == 2);
		if(frames > 0)
		{
			if(!smp.AllocateSample())
				throw std::runtime_error("sample allocation failed");
			if(bits == 16)
			{
				int16 *p = smp.sample16();
				for(size_t n = 0; n < data.size(); n++)
					p[n] = static_cast<int16>(std::lround(std::clamp(data[n], -1.0f, 1.0f) * 32767.0f));
			} else
			{
				int8 *p = smp.sample8();
				for(size_t n = 0; n < data.size(); n++)
					p[n] = static_cast<int8>(std::lround(std::clamp(data[n], -1.0f, 1.0f) * 127.0f));
			}
		}
		smp.SanitizeLoops();
		smp.PrecomputeLoops(*snd, false);
	}

	py::tuple SampleGetData(int i)
	{
		ModSample &smp = Smp(i, false);
		const size_t count = static_cast<size_t>(smp.nLength) * smp.GetNumChannels();
		std::vector<float> out(count);
		if(smp.HasSampleData())
		{
			if(smp.uFlags[CHN_16BIT])
			{
				const int16 *p = smp.sample16();
				for(size_t n = 0; n < count; n++)
					out[n] = p[n] / 32768.0f;
			} else
			{
				const int8 *p = smp.sample8();
				for(size_t n = 0; n < count; n++)
					out[n] = p[n] / 128.0f;
			}
		}
		return py::make_tuple(out, static_cast<int>(smp.GetNumChannels()));
	}

	py::dict SampleGet(int i)
	{
		ModSample &smp = Smp(i, false);
		py::dict d;
		d["name"] = std::string(snd->m_szNames[i]);
		d["length"] = smp.nLength;
		d["channels"] = static_cast<int>(smp.GetNumChannels());
		d["bits"] = smp.uFlags[CHN_16BIT] ? 16 : 8;
		d["c5_speed"] = smp.GetSampleRate(snd->GetType());
		d["volume"] = smp.nVolume / 4;
		d["global_volume"] = smp.nGlobalVol;
		d["pan"] = smp.uFlags[CHN_PANNING] ? py::object(py::int_(smp.nPan)) : py::object(py::none());
		d["relative_tone"] = smp.RelativeTone;
		d["finetune"] = smp.nFineTune;
		if(smp.uFlags[CHN_LOOP])
			d["loop"] = py::make_tuple(smp.nLoopStart, smp.nLoopEnd);
		else
			d["loop"] = py::none();
		d["pingpong"] = smp.uFlags[CHN_PINGPONGLOOP];
		if(smp.uFlags[CHN_SUSTAINLOOP])
			d["sustain_loop"] = py::make_tuple(smp.nSustainStart, smp.nSustainEnd);
		else
			d["sustain_loop"] = py::none();
		d["vibrato_type"] = static_cast<int>(smp.nVibType);
		d["vibrato_sweep"] = smp.nVibSweep;
		d["vibrato_depth"] = smp.nVibDepth;
		d["vibrato_rate"] = smp.nVibRate;
		if(smp.uFlags[CHN_ADLIB])
			d["opl"] = std::vector<int>(smp.adlib.begin(), smp.adlib.end());
		else
			d["opl"] = py::none();
		return d;
	}

	// OPL2/OPL3 FM instrument: 12 register bytes (see soundlib/OPL.cpp, OPL::Patch).
	void SampleSetOPL(int i, const std::vector<int> &patch)
	{
		if(!snd->SupportsOPL())
			throw py::value_error("OPL (FM) instruments need the s3m or mptm format");
		if(patch.size() != 12)
			throw py::value_error("OPL patch must have 12 bytes");
		ModSample &smp = Smp(i, true);
		OPLPatch p{};
		for(size_t n = 0; n < 12; n++)
			p[n] = static_cast<uint8>(std::clamp(patch[n], 0, 255));
		if(snd->GetType() == MOD_TYPE_S3M)
		{
			p[8] &= 0x03;  // S3M (OPL2) only knows waveforms 0-3
			p[9] &= 0x03;
		}
		smp.SetAdlib(true, p);
		if(!smp.nC5Speed)
			smp.nC5Speed = 8363;
		snd->InitOPL();
	}

	void SampleSet(int i, const py::dict &d)
	{
		ModSample &smp = Smp(i, true);
		if(d.contains("name"))
			snd->m_szNames[i] = d["name"].cast<std::string>();
		if(d.contains("c5_speed"))
		{
			smp.nC5Speed = std::clamp(d["c5_speed"].cast<uint32>(), uint32(1), uint32(10000000));
			if(snd->UseFinetuneAndTranspose())
				smp.FrequencyToTranspose();
		}
		if(d.contains("relative_tone"))
			smp.RelativeTone = static_cast<int8>(d["relative_tone"].cast<int>());
		if(d.contains("finetune"))
			smp.nFineTune = static_cast<int8>(d["finetune"].cast<int>());
		if(d.contains("relative_tone") || d.contains("finetune"))
		{
			if(snd->UseFinetuneAndTranspose())
				smp.TransposeToFrequency();
		}
		if(d.contains("volume"))
			smp.nVolume = static_cast<uint16>(std::clamp(d["volume"].cast<int>(), 0, 64) * 4);
		if(d.contains("global_volume"))
			smp.nGlobalVol = static_cast<uint16>(std::clamp(d["global_volume"].cast<int>(), 0, 64));
		if(d.contains("pan"))
		{
			if(d["pan"].is_none())
			{
				smp.uFlags.reset(CHN_PANNING);
			} else
			{
				smp.nPan = static_cast<uint16>(std::clamp(d["pan"].cast<int>(), 0, 256));
				smp.uFlags.set(CHN_PANNING);
			}
		}
		const bool pingpong = GetOr<bool>(d, "pingpong", smp.uFlags[CHN_PINGPONGLOOP]);
		if(d.contains("loop"))
		{
			if(d["loop"].is_none())
			{
				smp.SetLoop(0, 0, false, false, *snd);
			} else
			{
				auto lp = d["loop"].cast<std::pair<int64_t, int64_t>>();
				smp.SetLoop(static_cast<SmpLength>(std::max<int64_t>(0, lp.first)), static_cast<SmpLength>(std::max<int64_t>(0, lp.second)), true, pingpong, *snd);
			}
		} else if(d.contains("pingpong"))
		{
			smp.uFlags.set(CHN_PINGPONGLOOP, pingpong);
		}
		if(d.contains("sustain_loop"))
		{
			if(d["sustain_loop"].is_none())
			{
				smp.SetSustainLoop(0, 0, false, false, *snd);
			} else
			{
				auto lp = d["sustain_loop"].cast<std::pair<int64_t, int64_t>>();
				smp.SetSustainLoop(static_cast<SmpLength>(std::max<int64_t>(0, lp.first)), static_cast<SmpLength>(std::max<int64_t>(0, lp.second)), true, false, *snd);
			}
		}
		if(d.contains("vibrato_type"))
			smp.nVibType = static_cast<VibratoType>(std::clamp(d["vibrato_type"].cast<int>(), 0, 4));
		if(d.contains("vibrato_sweep"))
			smp.nVibSweep = static_cast<uint8>(std::clamp(d["vibrato_sweep"].cast<int>(), 0, 255));
		if(d.contains("vibrato_depth"))
			smp.nVibDepth = static_cast<uint8>(std::clamp(d["vibrato_depth"].cast<int>(), 0, 255));
		if(d.contains("vibrato_rate"))
			smp.nVibRate = static_cast<uint8>(std::clamp(d["vibrato_rate"].cast<int>(), 0, 255));
		smp.PrecomputeLoops(*snd, false);
	}

	// --- Instruments --------------------------------------------------------

	int NumInstruments() const { return snd->GetNumInstruments(); }

	ModInstrument &Ins(int i)
	{
		if(i < 1 || i > snd->GetNumInstruments() || snd->Instruments[i] == nullptr)
			throw py::index_error("instrument " + std::to_string(i) + " does not exist");
		return *snd->Instruments[i];
	}

	void InstrumentNew(int i, int sample)
	{
		const auto &specs = snd->GetModSpecifications();
		if(specs.instrumentsMax == 0)
			throw py::value_error("this format has no instruments; use samples directly");
		if(i < 1 || i > static_cast<int>(specs.instrumentsMax))
			throw py::index_error("instrument index must be 1.." + std::to_string(specs.instrumentsMax));
		// Fill gaps so indices stay contiguous
		for(int n = snd->GetNumInstruments() + 1; n < i; n++)
			if(snd->Instruments[n] == nullptr)
				snd->AllocateInstrument(static_cast<INSTRUMENTINDEX>(n), 0);
		ModInstrument *ins = snd->AllocateInstrument(static_cast<INSTRUMENTINDEX>(i), static_cast<SAMPLEINDEX>(std::max(0, sample)));
		if(!ins)
			throw std::runtime_error("instrument allocation failed");
		if(snd->GetType() == MOD_TYPE_XM)
		{
			ins->nFadeOut = 0;
		}
	}

	py::dict InstrumentGet(int i)
	{
		ModInstrument &ins = Ins(i);
		py::dict d;
		d["name"] = std::string(ins.name);
		d["fadeout"] = ins.nFadeOut;
		d["global_volume"] = ins.nGlobalVol;
		d["pan"] = ins.dwFlags[INS_SETPANNING] ? py::object(py::int_(ins.nPan)) : py::object(py::none());
		d["nna"] = static_cast<int>(ins.nNNA);
		d["dct"] = static_cast<int>(ins.nDCT);
		d["dna"] = static_cast<int>(ins.nDNA);
		d["resampling"] = static_cast<int>(ins.resampling);
		std::vector<int> kb(ins.Keyboard.begin(), ins.Keyboard.end());
		std::vector<int> nm(ins.NoteMap.begin(), ins.NoteMap.end());
		d["keyboard"] = kb;
		d["note_map"] = nm;
		d["filter_cutoff"] = ins.IsCutoffEnabled() ? py::object(py::int_(ins.GetCutoff())) : py::object(py::none());
		d["filter_resonance"] = ins.IsResonanceEnabled() ? py::object(py::int_(ins.GetResonance())) : py::object(py::none());
		d["plugin"] = static_cast<int>(ins.nMixPlug);
		d["volume_envelope"] = EnvelopeToPy(ins.VolEnv);
		d["panning_envelope"] = EnvelopeToPy(ins.PanEnv);
		d["pitch_envelope"] = EnvelopeToPy(ins.PitchEnv);
		return d;
	}

	void InstrumentSet(int i, const py::dict &d)
	{
		ModInstrument &ins = Ins(i);
		if(d.contains("name"))
			ins.name = d["name"].cast<std::string>();
		if(d.contains("fadeout"))
			ins.nFadeOut = static_cast<uint16>(std::clamp(d["fadeout"].cast<int>(), 0, 65535));
		if(d.contains("global_volume"))
			ins.nGlobalVol = static_cast<uint16>(std::clamp(d["global_volume"].cast<int>(), 0, 64));
		if(d.contains("pan"))
		{
			if(d["pan"].is_none())
			{
				ins.dwFlags.reset(INS_SETPANNING);
			} else
			{
				ins.nPan = static_cast<uint16>(std::clamp(d["pan"].cast<int>(), 0, 256));
				ins.dwFlags.set(INS_SETPANNING);
			}
		}
		if(d.contains("nna"))
			ins.nNNA = static_cast<NewNoteAction>(std::clamp(d["nna"].cast<int>(), 0, 3));
		if(d.contains("dct"))
			ins.nDCT = static_cast<DuplicateCheckType>(std::clamp(d["dct"].cast<int>(), 0, 4));
		if(d.contains("dna"))
			ins.nDNA = static_cast<DuplicateNoteAction>(std::clamp(d["dna"].cast<int>(), 0, 2));
		if(d.contains("resampling"))
			ins.resampling = static_cast<ResamplingMode>(d["resampling"].cast<int>());
		if(d.contains("sample"))
			ins.AssignSample(static_cast<SAMPLEINDEX>(d["sample"].cast<int>()));
		if(d.contains("keyboard"))
		{
			auto kb = d["keyboard"].cast<std::vector<int>>();
			for(size_t n = 0; n < std::min(kb.size(), ins.Keyboard.size()); n++)
				ins.Keyboard[n] = static_cast<SAMPLEINDEX>(std::max(0, kb[n]));
		}
		if(d.contains("note_map"))
		{
			auto nm = d["note_map"].cast<std::vector<int>>();
			for(size_t n = 0; n < std::min(nm.size(), ins.NoteMap.size()); n++)
				ins.NoteMap[n] = static_cast<uint8>(std::clamp(nm[n], int(NOTE_MIN), int(NOTE_MAX)));
		}
		if(d.contains("filter_cutoff"))
		{
			if(d["filter_cutoff"].is_none())
				ins.SetCutoff(0, false);
			else
				ins.SetCutoff(static_cast<uint8>(std::clamp(d["filter_cutoff"].cast<int>(), 0, 127)), true);
		}
		if(d.contains("filter_resonance"))
		{
			if(d["filter_resonance"].is_none())
				ins.SetResonance(0, false);
			else
				ins.SetResonance(static_cast<uint8>(std::clamp(d["filter_resonance"].cast<int>(), 0, 127)), true);
		}
		if(d.contains("plugin"))
			ins.nMixPlug = static_cast<PLUGINDEX>(std::clamp(d["plugin"].cast<int>(), 0, int(MAX_MIXPLUGINS)));
		if(d.contains("volume_envelope"))
			EnvelopeFromPy(ins.VolEnv, d["volume_envelope"].cast<py::dict>());
		if(d.contains("panning_envelope"))
			EnvelopeFromPy(ins.PanEnv, d["panning_envelope"].cast<py::dict>());
		if(d.contains("pitch_envelope"))
			EnvelopeFromPy(ins.PitchEnv, d["pitch_envelope"].cast<py::dict>());
	}

	// --- Plugins (built-in DMO emulations, DigiBooster/SymMOD echo, LFO) -----

	SNDMIXPLUGIN &Plug(int slot)
	{
		if(slot < 1 || slot > int(MAX_MIXPLUGINS))
			throw py::index_error("plugin slot must be 1.." + std::to_string(MAX_MIXPLUGINS));
		return snd->m_MixPlugins[slot - 1];
	}

	void PluginSet(int slot, uint32 id1, uint32 id2, const std::string &library, const std::string &name,
		const std::vector<float> &params, bool master, bool dryMix)
	{
		if(!snd->GetModSpecifications().supportsPlugins)
			throw py::value_error("this format cannot store plugins (use it, mptm or xm)");
		SNDMIXPLUGIN &plugin = Plug(slot);
		plugin.Destroy();
		plugin = SNDMIXPLUGIN{};
		plugin.Info.dwPluginId1 = static_cast<int32>(id1);
		plugin.Info.dwPluginId2 = static_cast<int32>(id2);
		plugin.Info.szLibraryName = library;
		plugin.Info.szName = name;
		plugin.SetMasterEffect(master);
		plugin.SetDryMix(dryMix);
		plugin.Info.gain = 10;
		CreateMixPluginProc(plugin, *snd);
		if(!plugin.pMixPlugin)
		{
			plugin = SNDMIXPLUGIN{};
			throw py::value_error("plugin '" + library + "' is not available in this build");
		}
		if(!plugin.pMixPlugin->GetNumInputChannels())
			plugin.SetExpandedMix(false);
		const auto numParams = plugin.pMixPlugin->GetNumParameters();
		for(size_t i = 0; i < params.size() && i < static_cast<size_t>(numParams); i++)
			plugin.pMixPlugin->SetParameter(static_cast<PlugParamIndex>(i), std::clamp(params[i], 0.0f, 1.0f));
		plugin.pMixPlugin->SaveAllParameters();
		snd->SetMixLevels(snd->GetMixLevels());  // recalculates plugin mix levels
	}

	void PluginSetParam(int slot, int index, float value)
	{
		SNDMIXPLUGIN &plugin = Plug(slot);
		if(!plugin.pMixPlugin)
			throw py::index_error("no plugin in slot " + std::to_string(slot));
		if(index < 0 || index >= static_cast<int>(plugin.pMixPlugin->GetNumParameters()))
			throw py::index_error("plugin parameter index out of range");
		plugin.pMixPlugin->SetParameter(static_cast<PlugParamIndex>(index), std::clamp(value, 0.0f, 1.0f));
		plugin.pMixPlugin->SaveAllParameters();
	}

	py::object PluginGet(int slot)
	{
		SNDMIXPLUGIN &plugin = Plug(slot);
		if(!plugin.IsValidPlugin())
			return py::none();
		py::dict d;
		d["id1"] = static_cast<uint32>(plugin.Info.dwPluginId1);
		d["id2"] = static_cast<uint32>(plugin.Info.dwPluginId2);
		d["library"] = std::string(plugin.Info.szLibraryName);
		d["name"] = std::string(plugin.Info.szName);
		d["master"] = plugin.IsMasterEffect();
		d["loaded"] = plugin.pMixPlugin != nullptr;
		std::vector<float> params;
		if(plugin.pMixPlugin)
			for(PlugParamIndex i = 0; i < plugin.pMixPlugin->GetNumParameters(); i++)
				params.push_back(plugin.pMixPlugin->GetParameter(i));
		d["params"] = params;
		return d;
	}

	void PluginRemove(int slot)
	{
		SNDMIXPLUGIN &plugin = Plug(slot);
		plugin.Destroy();
		plugin = SNDMIXPLUGIN{};
	}

	// --- Rendering ----------------------------------------------------------

	double Duration()
	{
		const auto lengths = snd->GetLength(eNoAdjust, GetLengthTarget(true).StartPos(snd->Order.GetCurrentSequenceIndex(), 0, 0));
		if(lengths.empty())
			return 0.0;
		return lengths.front().duration;
	}

	// Returns interleaved float32 PCM as bytes.
	py::bytes Render(int samplerate, int channels, int interpolation, int stereo_separation, double max_seconds, int repeat, int amiga)
	{
		if(samplerate < 8000 || samplerate > 192000)
			throw py::value_error("samplerate must be 8000..192000");
		if(channels != 1 && channels != 2)
			throw py::value_error("channels must be 1 or 2");
		CSoundFile &s = *snd;

		MixerSettings mix = s.m_MixerSettings;
		mix.gdwMixingFreq = static_cast<uint32>(samplerate);
		mix.gnChannels = static_cast<uint32>(channels);
		mix.m_nStereoSeparation = std::clamp(stereo_separation, 0, 256);
		s.SetMixerSettings(mix);

		CResamplerSettings rs;
		switch(interpolation)
		{
		case 0: rs.SrcMode = SRCMODE_NEAREST; break;
		case 1: rs.SrcMode = SRCMODE_LINEAR; break;
		case 2: rs.SrcMode = SRCMODE_CUBIC; break;
		default: rs.SrcMode = SRCMODE_SINC8LP; break;
		}
		// Paula (Amiga) resampler + output filter emulation; only affects Amiga-flagged songs (MOD).
		rs.emulateAmiga = static_cast<Resampling::AmigaFilter>(std::clamp(amiga, 0, 3));
		s.SetResamplerSettings(rs);

		s.PrecomputeSampleLoops(false);
		s.Order.SetSequence(s.Order.GetCurrentSequenceIndex());
		s.SetRepeatCount(std::max(0, repeat));
		s.ResetPlayPos();
		s.InitPlayer(true);
		s.SetCurrentOrder(0);
		s.m_bIsRendering = true;

		DithersWrapperOpenMPT dithers(mpt::global_prng(), 0 /* no dither for float output */, static_cast<std::size_t>(channels));

		const size_t maxFrames = static_cast<size_t>(std::max(0.0, max_seconds) * samplerate);
		std::vector<float> out;
		out.reserve(std::min<size_t>(maxFrames, static_cast<size_t>(samplerate) * 300) * channels);
		constexpr size_t chunk = 4096;
		std::vector<float> buffer(chunk * channels);
		size_t total = 0;
		{
			py::gil_scoped_release release;
			while(total < maxFrames)
			{
				const size_t want = std::min(chunk, maxFrames - total);
				AudioTargetBuffer<mpt::audio_span_interleaved<float>, DithersWrapperOpenMPT> target(mpt::audio_span_interleaved<float>(buffer.data(), static_cast<std::size_t>(channels), want), dithers);
				const size_t got = s.Read(static_cast<samplecount_t>(want), target);
				if(got == 0)
					break;
				out.insert(out.end(), buffer.begin(), buffer.begin() + got * channels);
				total += got;
			}
		}
		s.m_bIsRendering = false;
		return py::bytes(reinterpret_cast<const char *>(out.data()), out.size() * sizeof(float));
	}
};

}  // namespace

OPENMPT_NAMESPACE_END

using OpenMPT::Module;


PYBIND11_MODULE(_core, m)
{
	using namespace OpenMPT;
	m.doc() = "Low-level bindings to OpenMPT's sound engine (CSoundFile). Use the `mptscript` package for the friendly API.";

	m.attr("NOTE_NONE") = int(NOTE_NONE);
	m.attr("NOTE_MIN") = int(NOTE_MIN);
	m.attr("NOTE_MAX") = int(NOTE_MAX);
	m.attr("NOTE_MIDDLEC") = int(NOTE_MIDDLEC);
	m.attr("NOTE_KEYOFF") = int(NOTE_KEYOFF);
	m.attr("NOTE_NOTECUT") = int(NOTE_NOTECUT);
	m.attr("NOTE_FADE") = int(NOTE_FADE);

	py::dict effects;
#define MPT_EFF(x) effects[#x] = int(CMD_##x)
	MPT_EFF(NONE); MPT_EFF(ARPEGGIO); MPT_EFF(PORTAMENTOUP); MPT_EFF(PORTAMENTODOWN); MPT_EFF(TONEPORTAMENTO);
	MPT_EFF(VIBRATO); MPT_EFF(TONEPORTAVOL); MPT_EFF(VIBRATOVOL); MPT_EFF(TREMOLO); MPT_EFF(PANNING8);
	MPT_EFF(OFFSET); MPT_EFF(VOLUMESLIDE); MPT_EFF(POSITIONJUMP); MPT_EFF(VOLUME); MPT_EFF(PATTERNBREAK);
	MPT_EFF(RETRIG); MPT_EFF(SPEED); MPT_EFF(TEMPO); MPT_EFF(TREMOR); MPT_EFF(MODCMDEX); MPT_EFF(S3MCMDEX);
	MPT_EFF(CHANNELVOLUME); MPT_EFF(CHANNELVOLSLIDE); MPT_EFF(GLOBALVOLUME); MPT_EFF(GLOBALVOLSLIDE);
	MPT_EFF(KEYOFF); MPT_EFF(FINEVIBRATO); MPT_EFF(PANBRELLO); MPT_EFF(XFINEPORTAUPDOWN); MPT_EFF(PANNINGSLIDE);
	MPT_EFF(SETENVPOSITION); MPT_EFF(MIDI); MPT_EFF(SMOOTHMIDI); MPT_EFF(DELAYCUT); MPT_EFF(XPARAM);
	MPT_EFF(FINETUNE); MPT_EFF(FINETUNE_SMOOTH);
#undef MPT_EFF
	m.attr("EFFECTS") = effects;

	py::dict volcmds;
#define MPT_VOL(x) volcmds[#x] = int(VOLCMD_##x)
	MPT_VOL(NONE); MPT_VOL(VOLUME); MPT_VOL(PANNING); MPT_VOL(VOLSLIDEUP); MPT_VOL(VOLSLIDEDOWN);
	MPT_VOL(FINEVOLUP); MPT_VOL(FINEVOLDOWN); MPT_VOL(VIBRATOSPEED); MPT_VOL(VIBRATODEPTH);
	MPT_VOL(PANSLIDELEFT); MPT_VOL(PANSLIDERIGHT); MPT_VOL(TONEPORTAMENTO); MPT_VOL(PORTAUP);
	MPT_VOL(PORTADOWN); MPT_VOL(PLAYCONTROL); MPT_VOL(OFFSET);
#undef MPT_VOL
	m.attr("VOLCMDS") = volcmds;

	py::dict resampling;
	resampling["nearest"] = int(SRCMODE_NEAREST);
	resampling["linear"] = int(SRCMODE_LINEAR);
	resampling["cubic"] = int(SRCMODE_CUBIC);
	resampling["sinc"] = int(SRCMODE_SINC8LP);
	resampling["default"] = int(SRCMODE_DEFAULT);
	m.attr("RESAMPLING") = resampling;

	py::class_<Module>(m, "Module")
		.def_static("new", &Module::New, py::arg("format"), py::arg("channels"))
		.def_static("load", &Module::Load, py::arg("data"))
		.def("save", &Module::Save, py::arg("path"), py::arg("format") = std::string())
		.def_property_readonly("format", &Module::GetFormat)
		.def_property("title", &Module::GetTitle, &Module::SetTitle)
		.def_property("artist", &Module::GetArtist, &Module::SetArtist)
		.def_property("message", &Module::GetMessage, &Module::SetMessage)
		.def_property("tempo", &Module::GetTempo, &Module::SetTempo)
		.def_property("speed", &Module::GetSpeed, &Module::SetSpeed)
		.def_property("global_volume", &Module::GetGlobalVolume, &Module::SetGlobalVolume)
		.def_property("sample_preamp", &Module::GetSamplePreamp, &Module::SetSamplePreamp)
		.def_property("rows_per_beat", &Module::GetRowsPerBeat, &Module::SetRowsPerBeat)
		.def_property("rows_per_measure", &Module::GetRowsPerMeasure, &Module::SetRowsPerMeasure)
		.def_property("restart_position", &Module::GetRestartPos, &Module::SetRestartPos)
		.def_property("linear_slides", &Module::GetLinearSlides, &Module::SetLinearSlides)
		.def("limits", &Module::Limits)
		.def_property("num_channels", &Module::NumChannels, &Module::SetNumChannels)
		.def("channel_get", &Module::ChannelGet)
		.def("channel_set", &Module::ChannelSet)
		.def_property("order", &Module::GetOrder, &Module::SetOrder)
		.def_property_readonly("num_patterns", &Module::NumPatterns)
		.def("pattern_exists", &Module::PatternExists)
		.def("pattern_add", &Module::PatternAdd, py::arg("rows") = 64, py::arg("index") = -1)
		.def("pattern_duplicate", &Module::PatternDuplicate)
		.def("pattern_remove", &Module::PatternRemove)
		.def("pattern_rows", &Module::PatternRows)
		.def("pattern_resize", &Module::PatternResize)
		.def("pattern_get_name", &Module::PatternGetName)
		.def("pattern_set_name", &Module::PatternSetName)
		.def("pattern_clear", &Module::PatternClear)
		.def("pattern_get_data", &Module::PatternGetData)
		.def("pattern_set_data", &Module::PatternSetData)
		.def("cell_get", &Module::CellGet)
		.def("cell_set", &Module::CellSet, py::arg("pattern"), py::arg("row"), py::arg("channel"),
			py::arg("note") = 0, py::arg("instr") = 0, py::arg("volcmd") = 0, py::arg("vol") = 0, py::arg("command") = 0, py::arg("param") = 0)
		.def("effect_letter", &Module::EffectLetter)
		.def("vol_effect_letter", &Module::VolEffectLetter)
		.def("supports_effect", &Module::SupportsEffect)
		.def("supports_vol_effect", &Module::SupportsVolEffect)
		.def_property_readonly("num_samples", &Module::NumSamples)
		.def("sample_set_data", &Module::SampleSetData, py::arg("index"), py::arg("data"), py::arg("channels") = 1, py::arg("bits") = 16)
		.def("sample_get_data", &Module::SampleGetData)
		.def("sample_get", &Module::SampleGet)
		.def("sample_set", &Module::SampleSet)
		.def("sample_set_opl", &Module::SampleSetOPL, py::arg("index"), py::arg("patch"))
		.def("plugin_set", &Module::PluginSet, py::arg("slot"), py::arg("id1"), py::arg("id2"), py::arg("library"),
			py::arg("name"), py::arg("params"), py::arg("master") = false, py::arg("dry_mix") = false)
		.def("plugin_set_param", &Module::PluginSetParam)
		.def("plugin_get", &Module::PluginGet)
		.def("plugin_remove", &Module::PluginRemove)
		.def_property_readonly("num_instruments", &Module::NumInstruments)
		.def("instrument_new", &Module::InstrumentNew, py::arg("index"), py::arg("sample") = 0)
		.def("instrument_get", &Module::InstrumentGet)
		.def("instrument_set", &Module::InstrumentSet)
		.def("take_messages", &Module::TakeMessages, "Engine log messages since the last call: [(level, text)]")
		.def("duration", &Module::Duration)
		.def("render", &Module::Render, py::arg("samplerate") = 44100, py::arg("channels") = 2, py::arg("interpolation") = 3,
			py::arg("stereo_separation") = 128, py::arg("max_seconds") = 600.0, py::arg("repeat") = 0, py::arg("amiga") = 0);
}
