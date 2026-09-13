cmake_minimum_required(VERSION 3.10)
project(dslogic_cli C CXX)

set(CMAKE_C_STANDARD 99)
set(CMAKE_CXX_STANDARD 17)

add_definitions(-D_WIN32 -DHAVE_CONFIG_H)

set(DEPS_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../third_party/deps)
set(DSVIEW_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../third_party/DSView)

include_directories(
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${DSVIEW_DIR}/libsigrok4DSL
    ${DSVIEW_DIR}/libsigrok4DSL/hardware/DSL
    ${DSVIEW_DIR}/libsigrok4DSL/hardware/common
    ${DSVIEW_DIR}/common
    ${DEPS_DIR}/include
    ${DEPS_DIR}/include/libusb-1.0
    ${DEPS_DIR}/mingw64/include
    ${DEPS_DIR}/mingw64/include/glib-2.0
    ${DEPS_DIR}/mingw64/lib/glib-2.0/include
)

link_directories(
    ${DEPS_DIR}/MinGW64/dll
    ${DEPS_DIR}/MinGW64/static
    ${DEPS_DIR}/mingw64/lib
    ${DEPS_DIR}/mingw64/bin
)

set(LIBSIGROK_SOURCES
    ${DSVIEW_DIR}/libsigrok4DSL/backend.c
    ${DSVIEW_DIR}/libsigrok4DSL/dsdevice.c
    ${DSVIEW_DIR}/libsigrok4DSL/error.c
    ${DSVIEW_DIR}/libsigrok4DSL/hwdriver.c
    ${DSVIEW_DIR}/libsigrok4DSL/lib_main.c
    ${DSVIEW_DIR}/libsigrok4DSL/log.c
    ${DSVIEW_DIR}/libsigrok4DSL/session.c
    ${DSVIEW_DIR}/libsigrok4DSL/session_driver.c
    ${DSVIEW_DIR}/libsigrok4DSL/std.c
    ${DSVIEW_DIR}/libsigrok4DSL/strutil.c
    ${DSVIEW_DIR}/libsigrok4DSL/trigger.c
    ${DSVIEW_DIR}/libsigrok4DSL/version.c
    ${DSVIEW_DIR}/libsigrok4DSL/output/output.c
    ${DSVIEW_DIR}/libsigrok4DSL/input/input.c
    ${DSVIEW_DIR}/libsigrok4DSL/input/in_binary.c
    ${DSVIEW_DIR}/libsigrok4DSL/input/in_vcd.c
    ${DSVIEW_DIR}/libsigrok4DSL/input/in_wav.c
    ${DSVIEW_DIR}/libsigrok4DSL/output/csv.c
    ${DSVIEW_DIR}/libsigrok4DSL/output/gnuplot.c
    ${DSVIEW_DIR}/libsigrok4DSL/output/srzip.c
    ${DSVIEW_DIR}/libsigrok4DSL/output/vcd.c
    ${DSVIEW_DIR}/libsigrok4DSL/hardware/common/ezusb.c
    ${DSVIEW_DIR}/libsigrok4DSL/hardware/common/usb.c
    ${DSVIEW_DIR}/libsigrok4DSL/hardware/DSL/command.c
    ${DSVIEW_DIR}/libsigrok4DSL/hardware/DSL/dsl.c
    ${DSVIEW_DIR}/libsigrok4DSL/hardware/DSL/dslogic.c
    ${DSVIEW_DIR}/libsigrok4DSL/hardware/DSL/dscope.c
    ${DSVIEW_DIR}/libsigrok4DSL/hardware/demo/demo.c
    ${DSVIEW_DIR}/common/log/xlog.c
    ${DSVIEW_DIR}/common/minizip/zip.c
    ${DSVIEW_DIR}/common/minizip/unzip.c
    ${DSVIEW_DIR}/common/minizip/ioapi.c
)

add_executable(dslogic_cli
    main.cpp
    ${LIBSIGROK_SOURCES}
)

target_link_libraries(dslogic_cli
    glib-2.0
    ${DEPS_DIR}/MinGW64/dll/libusb-1.0.dll
    z
    ws2_32
    pthread
)

set_target_properties(dslogic_cli PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../runtime"
)
