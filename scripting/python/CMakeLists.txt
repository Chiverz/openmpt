cmake_minimum_required(VERSION 3.21)
project(mptscript LANGUAGES C CXX)

# Builds the `mptscript._core` Python extension from OpenMPT's sound engine
# (soundlib + common + src/openmpt). Same source set as libopenmpt in the root
# Makefile, minus libopenmpt's own API layer, plus file saving
# (LIBOPENMPT_BUILD_SCRIPTING, see common/BuildSettings.h).

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

get_filename_component(MPT_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)

find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)
find_package(pybind11 CONFIG REQUIRED)

file(GLOB MPT_ENGINE_SOURCES CONFIGURE_DEPENDS
	"${MPT_ROOT}/src/openmpt/all/*.cpp"
	"${MPT_ROOT}/src/openmpt/base/*.cpp"
	"${MPT_ROOT}/src/openmpt/logging/*.cpp"
	"${MPT_ROOT}/src/openmpt/random/*.cpp"
	"${MPT_ROOT}/src/openmpt/fileformat_base/*.cpp"
	"${MPT_ROOT}/src/openmpt/soundbase/*.cpp"
	"${MPT_ROOT}/src/openmpt/soundfile_data/*.cpp"
	"${MPT_ROOT}/src/openmpt/soundfile_write/*.cpp"
	"${MPT_ROOT}/common/*.cpp"
	"${MPT_ROOT}/soundlib/*.cpp"
	"${MPT_ROOT}/soundlib/plugins/*.cpp"
	"${MPT_ROOT}/soundlib/plugins/dmo/*.cpp"
	"${MPT_ROOT}/sounddsp/*.cpp"
)

# Engine as a static library so the binding TU stays small.
add_library(mpt_engine STATIC ${MPT_ENGINE_SOURCES})
target_include_directories(mpt_engine PUBLIC
	"${MPT_ROOT}"
	"${MPT_ROOT}/src"
	"${MPT_ROOT}/common"
	"${MPT_ROOT}/build/svn_version"
)
target_compile_definitions(mpt_engine PUBLIC
	LIBOPENMPT_BUILD
	LIBOPENMPT_BUILD_SCRIPTING
)

if(MSVC)
	target_compile_definitions(mpt_engine PUBLIC
		MPT_BUILD_MSVC WIN32 NOMINMAX UNICODE _UNICODE
		_CRT_NONSTDC_NO_WARNINGS _CRT_SECURE_NO_WARNINGS
		_CRT_SECURE_CPP_OVERLOAD_STANDARD_NAMES=1
		_CRT_SECURE_CPP_OVERLOAD_STANDARD_NAMES_COUNT=1
		_WIN32_WINNT=0x0A00 NTDDI_VERSION=0x0A000008
	)
	target_compile_options(mpt_engine PUBLIC /permissive- /Zc:preprocessor /Zc:__cplusplus /utf-8 /bigobj /EHsc /MP /W3 /wd4100 /wd4244 /wd4267)
else()
	target_compile_options(mpt_engine PUBLIC -fvisibility=hidden)
	find_package(Threads)
	if(Threads_FOUND)
		target_link_libraries(mpt_engine PUBLIC Threads::Threads)
	endif()
endif()

pybind11_add_module(_core MODULE src/bindings.cpp)
target_link_libraries(_core PRIVATE mpt_engine)
if(WIN32)
	target_link_libraries(_core PRIVATE winmm rpcrt4 ole32 bcrypt)
endif()

install(TARGETS _core LIBRARY DESTINATION mptscript RUNTIME DESTINATION mptscript)
