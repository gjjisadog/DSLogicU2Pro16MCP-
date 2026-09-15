#include "resource.h"

#include <windows.h>

#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace fs = std::filesystem;

struct InstallerArguments {
    bool uninstall = false;
    bool help = false;
    fs::path install_dir;
    fs::path home_dir;
};

static std::wstring quote_arg(const std::wstring &value) {
    // Windows filenames cannot contain a double quote, so quoting a path is
    // sufficient for the paths accepted by this installer.
    return L"\"" + value + L"\"";
}

static std::wstring environment_value(const wchar_t *name) {
    DWORD length = GetEnvironmentVariableW(name, nullptr, 0);
    if (length == 0) {
        return L"";
    }
    std::wstring value(length, L'\0');
    GetEnvironmentVariableW(name, value.data(), length);
    if (!value.empty() && value.back() == L'\0') {
        value.pop_back();
    }
    return value;
}

static fs::path default_install_dir() {
    std::wstring local_app_data = environment_value(L"LOCALAPPDATA");
    if (local_app_data.empty()) {
        throw std::runtime_error("LOCALAPPDATA is not available.");
    }
    return fs::path(local_app_data) / L"DSLogicU2Pro16MCP";
}

static InstallerArguments parse_arguments(int argc, wchar_t **argv) {
    InstallerArguments result;
    for (int index = 1; index < argc; ++index) {
        std::wstring argument(argv[index]);
        if (argument == L"/uninstall" || argument == L"--uninstall") {
            result.uninstall = true;
        } else if (argument == L"/help" || argument == L"/?" || argument == L"--help") {
            result.help = true;
        } else if (argument == L"/install-dir" || argument == L"--install-dir") {
            if (++index >= argc || std::wstring(argv[index]).empty()) {
                throw std::runtime_error("/install-dir requires a directory path.");
            }
            result.install_dir = fs::path(argv[index]);
        } else if (argument == L"/home" || argument == L"--home") {
            if (++index >= argc || std::wstring(argv[index]).empty()) {
                throw std::runtime_error("/home requires a user profile path.");
            }
            result.home_dir = fs::path(argv[index]);
        } else {
            throw std::runtime_error("Unknown installer option.");
        }
    }
    if (result.install_dir.empty()) {
        result.install_dir = default_install_dir();
    }
    return result;
}

static DWORD run_process(const fs::path &executable, const std::vector<std::wstring> &arguments) {
    std::wstring command_line = quote_arg(executable.wstring());
    for (const auto &argument : arguments) {
        command_line += L" ";
        command_line += quote_arg(argument);
    }
    std::vector<wchar_t> mutable_command(command_line.begin(), command_line.end());
    mutable_command.push_back(L'\0');

    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION process_info{};
    BOOL created = CreateProcessW(
        nullptr,
        mutable_command.data(),
        nullptr,
        nullptr,
        TRUE,
        0,
        nullptr,
        nullptr,
        &startup,
        &process_info);
    if (!created) {
        const std::string executable_text = executable.string();
        throw std::runtime_error("Could not start " + executable_text);
    }

    WaitForSingleObject(process_info.hProcess, INFINITE);
    DWORD exit_code = 1;
    GetExitCodeProcess(process_info.hProcess, &exit_code);
    CloseHandle(process_info.hThread);
    CloseHandle(process_info.hProcess);
    return exit_code;
}

static void extract_payload(const fs::path &zip_path) {
    HMODULE module = GetModuleHandleW(nullptr);
    HRSRC resource = FindResourceW(module, MAKEINTRESOURCEW(IDR_PAYLOAD), RT_RCDATA);
    if (!resource) {
        throw std::runtime_error("Embedded payload resource was not found.");
    }
    HGLOBAL loaded = LoadResource(module, resource);
    if (!loaded) {
        throw std::runtime_error("Embedded payload could not be loaded.");
    }
    DWORD size = SizeofResource(module, resource);
    const void *data = LockResource(loaded);
    if (!data || size == 0) {
        throw std::runtime_error("Embedded payload is empty.");
    }

    fs::create_directories(zip_path.parent_path());
    std::ofstream output(zip_path, std::ios::binary);
    if (!output) {
        throw std::runtime_error("Could not create temporary payload file.");
    }
    output.write(static_cast<const char *>(data), static_cast<std::streamsize>(size));
    if (!output) {
        throw std::runtime_error("Could not write temporary payload file.");
    }
}

static fs::path make_temp_directory() {
    wchar_t temp_path[MAX_PATH]{};
    DWORD length = GetTempPathW(MAX_PATH, temp_path);
    if (length == 0 || length >= MAX_PATH) {
        throw std::runtime_error("Could not resolve the Windows temporary directory.");
    }
    fs::path directory = fs::path(temp_path) / (L"dslogic-mcp-" + std::to_wstring(GetCurrentProcessId()));
    directory += L"-" + std::to_wstring(GetTickCount64());
    fs::create_directories(directory);
    return directory;
}

static void extract_zip_with_powershell(const fs::path &zip_path, const fs::path &destination) {
    fs::path powershell = fs::path(environment_value(L"WINDIR")) /
        L"System32\\WindowsPowerShell\\v1.0\\powershell.exe";
    if (!fs::exists(powershell)) {
        throw std::runtime_error("Windows PowerShell was not found.");
    }
    std::vector<std::wstring> arguments = {
        L"-NoProfile",
        L"-ExecutionPolicy", L"Bypass",
        L"-Command",
        L"& { Expand-Archive -LiteralPath $args[0] -DestinationPath $args[1] -Force }",
        zip_path.wstring(),
        destination.wstring(),
    };
    DWORD exit_code = run_process(powershell, arguments);
    if (exit_code != 0) {
        throw std::runtime_error("PowerShell failed to extract the offline payload.");
    }
}

static void copy_directory(const fs::path &source, const fs::path &destination) {
    fs::create_directories(destination);
    for (const auto &entry : fs::recursive_directory_iterator(source)) {
        fs::path relative = fs::relative(entry.path(), source);
        fs::path target = destination / relative;
        if (entry.is_directory()) {
            fs::create_directories(target);
        } else if (entry.is_regular_file()) {
            fs::create_directories(target.parent_path());
            fs::copy_file(entry.path(), target, fs::copy_options::overwrite_existing);
        }
    }
}

static void delete_directory(const fs::path &directory) {
    std::error_code error;
    fs::remove_all(directory, error);
}

static int install(const fs::path &install_dir, const fs::path &home_dir) {
    fs::path temporary = make_temp_directory();
    try {
        fs::path zip_path = temporary / L"payload.zip";
        fs::path extracted = temporary / L"payload";
        std::wcout << L"Installing DSLogic U2Pro16 MCP to " << install_dir.wstring() << L"\n";
        extract_payload(zip_path);
        extract_zip_with_powershell(zip_path, extracted);
        copy_directory(extracted, install_dir);

        fs::path server = install_dir / L"dslogic-mcp.exe";
        if (!fs::exists(server)) {
            throw std::runtime_error("The packaged MCP executable was not found after extraction.");
        }
        std::vector<std::wstring> arguments = {
            L"--install", L"--targets", L"all",
            L"--app-root", install_dir.wstring(),
            L"--executable", server.wstring(),
        };
        if (!home_dir.empty()) {
            arguments.push_back(L"--home");
            arguments.push_back(home_dir.wstring());
        }
        DWORD exit_code = run_process(server, arguments);
        if (exit_code != 0) {
            throw std::runtime_error("Agent configuration registration failed.");
        }
        std::wcout << L"Installation complete. Restart your Agent to reload MCP servers.\n";
        delete_directory(temporary);
        return 0;
    } catch (...) {
        delete_directory(temporary);
        throw;
    }
}

static int uninstall(const fs::path &install_dir, const fs::path &home_dir) {
    fs::path server = install_dir / L"dslogic-mcp.exe";
    if (!fs::exists(server)) {
        std::wcout << L"No installation found at " << install_dir.wstring() << L".\n";
        return 0;
    }
    std::vector<std::wstring> arguments = {L"--uninstall", L"--targets", L"all"};
    if (!home_dir.empty()) {
        arguments.push_back(L"--home");
        arguments.push_back(home_dir.wstring());
    }
    DWORD exit_code = run_process(server, arguments);
    if (exit_code != 0) {
        return static_cast<int>(exit_code);
    }
    std::wcout << L"MCP registrations removed. The application directory and captures were kept at "
               << install_dir.wstring() << L".\n";
    return 0;
}

static void print_help() {
    std::wcout << L"DSLogic U2Pro16 MCP offline installer\n"
               << L"  DSLogicU2Pro16MCP-Setup.exe                 Install for the current user\n"
               << L"  DSLogicU2Pro16MCP-Setup.exe /install-dir X  Install to X\n"
               << L"  DSLogicU2Pro16MCP-Setup.exe /home X          Use profile X for Agent configs\n"
               << L"  DSLogicU2Pro16MCP-Setup.exe /uninstall      Remove Agent registrations\n";
}

int wmain(int argc, wchar_t **argv) {
    try {
        InstallerArguments arguments = parse_arguments(argc, argv);
        if (arguments.help) {
            print_help();
            return 0;
        }
        return arguments.uninstall
            ? uninstall(arguments.install_dir, arguments.home_dir)
            : install(arguments.install_dir, arguments.home_dir);
    } catch (const std::exception &error) {
        std::cerr << "Installation failed: " << error.what() << "\n";
        return 1;
    }
}
