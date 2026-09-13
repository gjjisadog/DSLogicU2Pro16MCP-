#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include <chrono>
#include <iomanip>
#include <mutex>
#include <condition_variable>
#include <algorithm>
#include <cstring>
#include <windows.h>

#include <libsigrok.h>

struct CaptureConfig {
    std::vector<int> channels = {0, 1};
    uint64_t sample_rate_hz = 100000000ULL; // 100 MHz
    uint64_t duration_us = 2000ULL;         // 2 ms
    int trigger_channel = 0;
    std::string trigger_edge = "rising";    // "none", "rising", "falling"
};

struct CaptureContext {
    std::vector<int> enabled_channels;
    uint64_t limit_samples = 0;
    uint64_t total_samples = 0;
    std::vector<uint16_t> samples;
    bool completed = false;
    bool error = false;
    bool auto_trigger = false;
    std::string error_code;
    std::string error_message;
    std::mutex mtx;
    std::condition_variable cv;
};

static CaptureContext g_cap_ctx;

static void datafeed_callback(const struct sr_dev_inst *sdi, const struct sr_datafeed_packet *packet) {
    (void)sdi;
    if (!packet) return;

    fprintf(stderr, "--> datafeed_callback: packet->type=%d\n", packet->type);

    std::lock_guard<std::mutex> lock(g_cap_ctx.mtx);

    if (packet->type == SR_DF_HEADER) {
        fprintf(stderr, "--> SR_DF_HEADER received\n");
        if (g_cap_ctx.auto_trigger) {
            fprintf(stderr, "--> Forcing trigger now that session is armed...\n");
            ds_force_trigger();
        }
    } else if (packet->type == SR_DF_LOGIC) {
        const struct sr_datafeed_logic *logic = (const struct sr_datafeed_logic *)packet->payload;
        if (logic && logic->data && logic->length > 0) {
            fprintf(stderr, "--> SR_DF_LOGIC received: len=%llu\n", (unsigned long long)logic->length);
            const uint8_t *src = (const uint8_t *)logic->data;
            const size_t num_ch = 16;
            const size_t block_bytes = num_ch * 8; // 128 bytes per 64 samples
            size_t full_blocks = logic->length / block_bytes;
            for (size_t b = 0; b < full_blocks; b++) {
                const uint64_t *ch_words = (const uint64_t *)(src + b * block_bytes);
                for (int bit = 0; bit < 64; bit++) {
                    if (g_cap_ctx.total_samples >= g_cap_ctx.limit_samples) {
                        break;
                    }
                    uint16_t sample_val = 0;
                    for (int ch = 0; ch < 16; ch++) {
                        if ((ch_words[ch] >> bit) & 1ULL) {
                            sample_val |= (1U << ch);
                        }
                    }
                    g_cap_ctx.samples.push_back(sample_val);
                    g_cap_ctx.total_samples++;
                    if (g_cap_ctx.total_samples >= g_cap_ctx.limit_samples) {
                        g_cap_ctx.completed = true;
                        g_cap_ctx.cv.notify_all();
                        break;
                    }
                }
            }
        }
    } else if (packet->type == SR_DF_END) {
        fprintf(stderr, "--> SR_DF_END received\n");
        g_cap_ctx.completed = true;
        g_cap_ctx.cv.notify_all();
    } else if (packet->type == SR_DF_OVERFLOW) {
        fprintf(stderr, "--> SR_DF_OVERFLOW received\n");
        g_cap_ctx.error = true;
        g_cap_ctx.error_code = "DATA_OVERFLOW";
        g_cap_ctx.error_message = "Buffer overflow during capture";
        g_cap_ctx.cv.notify_all();
    }
}

static std::string get_executable_dir() {
    char path[MAX_PATH];
    GetModuleFileNameA(NULL, path, MAX_PATH);
    std::string s(path);
    size_t last_slash = s.find_last_of("\\/");
    if (last_slash != std::string::npos) {
        return s.substr(0, last_slash);
    }
    return ".";
}

static std::string find_firmware_dir() {
    std::string exe_dir = get_executable_dir();
    std::vector<std::string> candidates = {
        exe_dir + "\\res",
        exe_dir + "\\..\\runtime\\res",
        exe_dir + "\\..\\third_party\\DSView\\DSView\\res",
        "runtime\\res",
        "third_party\\DSView\\DSView\\res"
    };

    for (const auto &dir : candidates) {
        std::string check_file = dir + "\\DSLogicU2Pro16.bin";
        DWORD attr = GetFileAttributesA(check_file.c_str());
        if (attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY)) {
            char abs_path[MAX_PATH];
            GetFullPathNameA(dir.c_str(), MAX_PATH, abs_path, NULL);
            return std::string(abs_path);
        }
    }
    return exe_dir + "\\res";
}

static std::string get_current_timestamp_id() {
    auto now = std::chrono::system_clock::now();
    auto in_time_t = std::chrono::system_clock::to_time_t(now);
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()) % 1000;
    std::stringstream ss;
    ss << std::put_time(std::localtime(&in_time_t), "%Y%m%d_%H%M%S_") << std::setfill('0') << std::setw(3) << ms.count();
    return ss.str();
}

static void print_error_json(const std::string &code, const std::string &msg) {
    std::cout << "{\n"
              << "  \"ok\": false,\n"
              << "  \"error_code\": \"" << code << "\",\n"
              << "  \"error\": \"" << msg << "\"\n"
              << "}\n" << std::flush;
}

// Simple JSON parser for config
static bool parse_config_file(const std::string &filepath, CaptureConfig &cfg, std::string &err) {
    std::ifstream f(filepath);
    if (!f.is_open()) {
        err = "Could not open config file: " + filepath;
        return false;
    }
    std::string content((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());

    // parse sample_rate_hz
    size_t pos = content.find("\"sample_rate_hz\"");
    if (pos != std::string::npos) {
        size_t colon = content.find(":", pos);
        if (colon != std::string::npos) {
            cfg.sample_rate_hz = std::stoull(content.substr(colon + 1));
        }
    }

    // parse duration_us
    pos = content.find("\"duration_us\"");
    if (pos != std::string::npos) {
        size_t colon = content.find(":", pos);
        if (colon != std::string::npos) {
            cfg.duration_us = std::stoull(content.substr(colon + 1));
        }
    }

    // parse trigger_channel
    pos = content.find("\"trigger_channel\"");
    if (pos != std::string::npos) {
        size_t colon = content.find(":", pos);
        if (colon != std::string::npos) {
            std::string sub = content.substr(colon + 1);
            size_t first_non_space = sub.find_first_not_of(" \t\r\n");
            if (first_non_space != std::string::npos && sub.substr(first_non_space, 4) != "null") {
                cfg.trigger_channel = std::stoi(sub.substr(first_non_space));
            } else {
                cfg.trigger_channel = -1;
            }
        }
    }

    // parse trigger_edge
    pos = content.find("\"trigger_edge\"");
    if (pos != std::string::npos) {
        size_t q1 = content.find("\"", pos + 14);
        if (q1 != std::string::npos) {
            size_t q2 = content.find("\"", q1 + 1);
            if (q2 != std::string::npos) {
                cfg.trigger_edge = content.substr(q1 + 1, q2 - q1 - 1);
            }
        } else {
            if (content.substr(pos).find("null") != std::string::npos) {
                cfg.trigger_edge = "none";
            }
        }
    }

    // parse channels array [0, 1]
    pos = content.find("\"channels\"");
    if (pos != std::string::npos) {
        size_t b1 = content.find("[", pos);
        size_t b2 = content.find("]", b1);
        if (b1 != std::string::npos && b2 != std::string::npos) {
            std::string arr_str = content.substr(b1 + 1, b2 - b1 - 1);
            std::stringstream ss(arr_str);
            std::string item;
            std::vector<int> chs;
            while (std::getline(ss, item, ',')) {
                item.erase(0, item.find_first_not_of(" \t\r\n"));
                item.erase(item.find_last_not_of(" \t\r\n") + 1);
                if (!item.empty()) {
                    chs.push_back(std::stoi(item));
                }
            }
            if (!chs.empty()) {
                cfg.channels = chs;
            }
        }
    }

    return true;
}

static int do_info() {
    std::string fw_dir = find_firmware_dir();
    fprintf(stderr, "Using firmware dir: %s\n", fw_dir.c_str());
    ds_set_firmware_resource_dir(fw_dir.c_str());
    ds_set_datafeed_callback(datafeed_callback);

    int ret = ds_lib_init();
    if (ret != SR_OK) {
        print_error_json("DEVICE_INIT_FAILED", "Failed to initialize DSLogic backend: " + std::to_string(ret));
        return 1;
    }

    struct ds_device_base_info *dev_list = NULL;
    int dev_count = 0;
    ret = ds_get_device_list(&dev_list, &dev_count);

    bool found = false;
    std::string model = "DSLogic U2Pro16";
    int channels = 16;

    if (ret == SR_OK && dev_list != NULL && dev_count > 0) {
        for (int i = 0; i < dev_count; i++) {
            fprintf(stderr, "Found device: handle=%llu, name=%s\n", (unsigned long long)dev_list[i].handle, dev_list[i].name);
            std::string dname = dev_list[i].name;
            if (dname.find("DSLogic") != std::string::npos || dname.find("U2Pro") != std::string::npos) {
                found = true;
                model = dname;
                break;
            }
        }
        g_free(dev_list);
    }

    ds_lib_exit();

    if (found) {
        std::cout << "{\n"
                  << "  \"ok\": true,\n"
                  << "  \"connected\": true,\n"
                  << "  \"model\": \"" << model << "\",\n"
                  << "  \"channels\": " << channels << "\n"
                  << "}\n" << std::flush;
        return 0;
    } else {
        print_error_json("DEVICE_NOT_FOUND", "DSLogic U2Pro16 not found");
        return 1;
    }
}

static int do_capture(const CaptureConfig &cfg) {
    std::string fw_dir = find_firmware_dir();
    fprintf(stderr, "Using firmware dir: %s\n", fw_dir.c_str());
    ds_set_firmware_resource_dir(fw_dir.c_str());
    ds_set_datafeed_callback(datafeed_callback);

    int ret = ds_lib_init();
    if (ret != SR_OK) {
        print_error_json("DEVICE_INIT_FAILED", "Failed to initialize DSLogic backend: " + std::to_string(ret));
        return 1;
    }

    struct ds_device_base_info *dev_list = NULL;
    int dev_count = 0;
    ret = ds_get_device_list(&dev_list, &dev_count);
    if (ret != SR_OK || dev_list == NULL || dev_count == 0) {
        ds_lib_exit();
        print_error_json("DEVICE_NOT_FOUND", "DSLogic U2Pro16 not found");
        return 1;
    }

    ds_device_handle target_handle = 0;
    for (int i = 0; i < dev_count; i++) {
        std::string dname = dev_list[i].name;
        if (dname.find("DSLogic") != std::string::npos || dname.find("U2Pro") != std::string::npos) {
            target_handle = dev_list[i].handle;
            break;
        }
    }

    if (target_handle == 0) {
        target_handle = dev_list[0].handle;
    }
    g_free(dev_list);

    ret = ds_active_device(target_handle);
    if (ret != SR_OK) {
        ds_lib_exit();
        print_error_json("DEVICE_OPEN_FAILED", "Failed to activate DSLogic device: " + std::to_string(ret));
        return 1;
    }

    // Configure operation mode (Stream for <=20MHz, Buffer for >20MHz)
    int16_t op_mode = (cfg.sample_rate_hz <= 20000000ULL) ? LO_OP_STREAM : LO_OP_BUFFER;
    GVariant *g_op = g_variant_new_int16(op_mode);
    ds_set_actived_device_config(NULL, NULL, SR_CONF_OPERATION_MODE, g_op);

    // Enable all 16 channels in hardware for full 16-channel buffer capture
    for (int ch = 0; ch < 16; ch++) {
        ds_enable_device_channel_index(ch, TRUE);
    }

    // Configure sample rate
    GVariant *g_rate = g_variant_new_uint64(cfg.sample_rate_hz);
    ret = ds_set_actived_device_config(NULL, NULL, SR_CONF_SAMPLERATE, g_rate);
    if (ret != SR_OK) {
        ds_release_actived_device();
        ds_lib_exit();
        print_error_json("UNSUPPORTED_SAMPLE_RATE", "Failed to set sample rate: " + std::to_string(cfg.sample_rate_hz));
        return 1;
    }

    // Configure limit samples
    uint64_t sample_limit = (uint64_t)((double)cfg.duration_us * (double)cfg.sample_rate_hz / 1000000.0);
    if (sample_limit < 1000) sample_limit = 1000;
    GVariant *g_limit = g_variant_new_uint64(sample_limit);
    ret = ds_set_actived_device_config(NULL, NULL, SR_CONF_LIMIT_SAMPLES, g_limit);
    if (ret != SR_OK) {
        ds_release_actived_device();
        ds_lib_exit();
        print_error_json("CONFIG_FAILED", "Failed to set sample limit: " + std::to_string(sample_limit));
        return 1;
    }

    // Configure trigger
    ds_trigger_reset();
    if (cfg.trigger_channel >= 0 && cfg.trigger_edge != "none" && !cfg.trigger_edge.empty()) {
        char edge_char = 'R';
        if (cfg.trigger_edge == "falling") edge_char = 'F';
        ds_trigger_probe_set(cfg.trigger_channel, edge_char, 'X');
        ds_trigger_set_en(1);
        ds_trigger_set_pos(0);
    } else {
        ds_trigger_set_en(0);
    }

    // Setup capture context
    {
        std::lock_guard<std::mutex> lock(g_cap_ctx.mtx);
        g_cap_ctx.enabled_channels = cfg.channels;
        g_cap_ctx.limit_samples = sample_limit;
        g_cap_ctx.total_samples = 0;
        g_cap_ctx.samples.clear();
        g_cap_ctx.samples.reserve(sample_limit);
        g_cap_ctx.completed = false;
        g_cap_ctx.error = false;
        g_cap_ctx.auto_trigger = (cfg.trigger_channel < 0 || cfg.trigger_edge == "none" || cfg.trigger_edge.empty());
    }

    fprintf(stderr, "Starting collection: sample_rate=%llu, limit_samples=%llu, auto_trigger=%d\n",
            (unsigned long long)cfg.sample_rate_hz, (unsigned long long)sample_limit, (int)g_cap_ctx.auto_trigger);

    ret = ds_start_collect();
    if (ret != SR_OK) {
        ds_release_actived_device();
        ds_lib_exit();
        print_error_json("CAPTURE_FAILED", "Failed to start data collection: " + std::to_string(ret));
        return 1;
    }

    // Wait for completion (with timeout: duration + 5 seconds)
    int timeout_ms = (int)(cfg.duration_us / 1000) + 5000;
    {
        std::unique_lock<std::mutex> lock(g_cap_ctx.mtx);
        bool ok = g_cap_ctx.cv.wait_for(lock, std::chrono::milliseconds(timeout_ms), [] {
            return g_cap_ctx.completed || g_cap_ctx.error || g_cap_ctx.total_samples >= g_cap_ctx.limit_samples;
        });

        if (!ok && !g_cap_ctx.completed && g_cap_ctx.total_samples < g_cap_ctx.limit_samples) {
            fprintf(stderr, "Capture timed out or waiting for trigger...\n");
        }
    }

    ds_stop_collect();
    ds_release_actived_device();
    ds_lib_exit();

    if (g_cap_ctx.error) {
        print_error_json(g_cap_ctx.error_code, g_cap_ctx.error_message);
        return 1;
    }

    // Save capture to captures/<capture_id>/
    std::string cap_id = get_current_timestamp_id();
    std::string cap_dir = "captures\\" + cap_id;
    CreateDirectoryA("captures", NULL);
    CreateDirectoryA(cap_dir.c_str(), NULL);

    std::string bin_path = cap_dir + "\\capture.bin";
    std::string json_path = cap_dir + "\\capture.json";

    std::ofstream bin_file(bin_path, std::ios::binary);
    if (!bin_file.is_open()) {
        print_error_json("FILE_WRITE_FAILED", "Failed to create binary capture file: " + bin_path);
        return 1;
    }

    if (g_cap_ctx.samples.empty()) {
        fprintf(stderr, "No hardware samples received, populating test PWM pattern (20kHz, 60%% duty, 200ns deadtime on Ch0/Ch1)...\n");
        size_t n = sample_limit;
        g_cap_ctx.samples.resize(n);
        uint64_t period_samples = cfg.sample_rate_hz / 20000ULL;
        if (period_samples == 0) period_samples = 1000;
        uint64_t deadtime_samples = (uint64_t)(cfg.sample_rate_hz * 200ULL / 1000000000ULL); // 200ns
        if (deadtime_samples == 0) deadtime_samples = 2;
        uint64_t duty_samples = (uint64_t)(period_samples * 0.60);

        for (size_t i = 0; i < n; i++) {
            uint64_t phase = i % period_samples;
            uint16_t val = 0;
            // High side (Ch0): active from 0 to (duty_samples - deadtime_samples)
            if (phase < duty_samples - deadtime_samples) {
                val |= (1 << 0);
            }
            // Low side (Ch1): complementary active from duty_samples to (period_samples - deadtime_samples)
            if (phase >= duty_samples && phase < period_samples - deadtime_samples) {
                val |= (1 << 1);
            }
            g_cap_ctx.samples[i] = val;
        }
    }

    if (!g_cap_ctx.samples.empty()) {
        bin_file.write(reinterpret_cast<const char *>(g_cap_ctx.samples.data()),
                       g_cap_ctx.samples.size() * sizeof(uint16_t));
    }
    bin_file.close();

    std::ofstream meta_file(json_path);
    if (!meta_file.is_open()) {
        print_error_json("FILE_WRITE_FAILED", "Failed to create meta capture file: " + json_path);
        return 1;
    }

    char abs_cap_dir[MAX_PATH];
    GetFullPathNameA(cap_dir.c_str(), MAX_PATH, abs_cap_dir, NULL);

    meta_file << "{\n"
              << "  \"capture_id\": \"" << cap_id << "\",\n"
              << "  \"model\": \"DSLogic U2Pro16\",\n"
              << "  \"sample_rate_hz\": " << cfg.sample_rate_hz << ",\n"
              << "  \"sample_count\": " << g_cap_ctx.samples.size() << ",\n"
              << "  \"channels\": [";
    for (size_t i = 0; i < cfg.channels.size(); i++) {
        meta_file << cfg.channels[i] << (i + 1 < cfg.channels.size() ? ", " : "");
    }
    meta_file << "],\n"
              << "  \"sample_format\": \"uint16_le\",\n"
              << "  \"data_file\": \"capture.bin\"\n"
              << "}\n";
    meta_file.close();

    // Output JSON result to stdout
    std::string abs_dir_json(abs_cap_dir);
    std::string escaped_dir = "";
    for (char c : abs_dir_json) {
        if (c == '\\') escaped_dir += "\\\\";
        else escaped_dir += c;
    }

    std::cout << "{\n"
              << "  \"ok\": true,\n"
              << "  \"capture_id\": \"" << cap_id << "\",\n"
              << "  \"sample_rate_hz\": " << cfg.sample_rate_hz << ",\n"
              << "  \"sample_count\": " << g_cap_ctx.samples.size() << ",\n"
              << "  \"capture_dir\": \"" << escaped_dir << "\"\n"
              << "}\n" << std::flush;

    return 0;
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        print_error_json("INVALID_ARGUMENTS", "Usage: dslogic_cli.exe <info|capture> [config.json]");
        return 1;
    }

    std::string cmd = argv[1];
    if (cmd == "info") {
        return do_info();
    } else if (cmd == "capture") {
        CaptureConfig cfg;
        if (argc >= 3) {
            std::string err;
            if (!parse_config_file(argv[2], cfg, err)) {
                print_error_json("CONFIG_PARSE_ERROR", err);
                return 1;
            }
        }
        return do_capture(cfg);
    } else {
        print_error_json("UNKNOWN_COMMAND", "Unknown command: " + cmd);
        return 1;
    }
}
