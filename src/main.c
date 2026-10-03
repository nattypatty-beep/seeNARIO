// VisionNav Assistant - Raspberry Pi
// Build: gcc main.c -o visionnav -lcurl
// Run:   export GEMINI_API_KEY=... ELEVENLABS_API_KEY=... && ./visionnav
// Deps:  sudo apt install libcurl4-openssl-dev fswebcam mpg123

#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <signal.h>
#include <unistd.h>
#include <time.h>
#include <curl/curl.h>

#define IMAGE_FILE "scene.jpg"
#define AUDIO_FILE "alert.mp3"
#define LOG_FILE "logs.json"
#define ELEVENLABS_VOICE_ID "21m00Tcm4TlvDq8ikWAM" // Rachel
#define CYCLE_SECONDS 2.5

#define GEMINI_URL "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

#define SYSTEM_PROMPT \
    "You are a navigation aid for a visually impaired walker. Look at the camera view. " \
    "Name the nearest hazard in the walking path, its direction (left, center, right) and " \
    "whether it is close or far. Max 6 words, e.g. 'Chair ahead, center, close'. " \
    "If the path is safe, reply exactly: Path clear"

static volatile sig_atomic_t running = 1;
static void on_sigint(int s) { (void)s; running = 0; }

struct MemoryBlock { char *memory; size_t size; };

static size_t write_memory_callback(void *contents, size_t size, size_t nmemb, void *userp) {
    size_t realsize = size * nmemb;
    struct MemoryBlock *mem = (struct MemoryBlock *)userp;
    char *ptr = realloc(mem->memory, mem->size + realsize + 1);
    if (!ptr) return 0;
    mem->memory = ptr;
    memcpy(&mem->memory[mem->size], contents, realsize);
    mem->size += realsize;
    mem->memory[mem->size] = 0;
    return realsize;
}

static size_t write_audio_callback(void *ptr, size_t size, size_t nmemb, FILE *stream) {
    return fwrite(ptr, size, nmemb, stream);
}

// ---------- helpers ----------

static const char B64[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static char *base64_encode(const unsigned char *in, size_t len) {
    char *out = malloc(4 * ((len + 2) / 3) + 1);
    if (!out) return NULL;
    size_t i = 0, j = 0;
    while (i + 2 < len) {
        uint32_t v = ((uint32_t)in[i] << 16) | ((uint32_t)in[i + 1] << 8) | in[i + 2];
        out[j++] = B64[(v >> 18) & 63]; out[j++] = B64[(v >> 12) & 63];
        out[j++] = B64[(v >> 6) & 63];  out[j++] = B64[v & 63];
        i += 3;
    }
    if (len - i == 1) {
        uint32_t v = (uint32_t)in[i] << 16;
        out[j++] = B64[(v >> 18) & 63]; out[j++] = B64[(v >> 12) & 63];
        out[j++] = '='; out[j++] = '=';
    } else if (len - i == 2) {
        uint32_t v = ((uint32_t)in[i] << 16) | ((uint32_t)in[i + 1] << 8);
        out[j++] = B64[(v >> 18) & 63]; out[j++] = B64[(v >> 12) & 63];
        out[j++] = B64[(v >> 6) & 63];  out[j++] = '=';
    }
    out[j] = 0;
    return out;
}

static unsigned char *read_file(const char *path, size_t *len) {
    FILE *fp = fopen(path, "rb");
    if (!fp) return NULL;
    fseek(fp, 0, SEEK_END);
    long n = ftell(fp);
    rewind(fp);
    if (n <= 0) { fclose(fp); return NULL; }
    unsigned char *buf = malloc((size_t)n);
    if (buf && fread(buf, 1, (size_t)n, fp) != (size_t)n) { free(buf); buf = NULL; }
    fclose(fp);
    if (buf) *len = (size_t)n;
    return buf;
}

// Escape a string for safe embedding inside a JSON string literal
static void json_escape(const char *in, char *out, size_t max) {
    size_t j = 0;
    for (size_t i = 0; in[i] && j + 7 < max; i++) {
        unsigned char c = (unsigned char)in[i];
        if (c == '"' || c == '\\') { out[j++] = '\\'; out[j++] = (char)c; }
        else if (c < 0x20)         { j += (size_t)snprintf(out + j, max - j, "\\u%04x", c); }
        else                       { out[j++] = (char)c; }
    }
    out[j] = 0;
}

// Pull the first "text" string value out of Gemini's response
static int extract_gemini_text(const char *json, char *out, size_t max) {
    const char *p = strstr(json, "\"text\"");
    if (!p) return 0;
    p += 6;
    while (*p == ' ' || *p == ':' || *p == '\n' || *p == '\r' || *p == '\t') p++;
    if (*p != '"') return 0;
    p++;
    size_t i = 0;
    while (*p && *p != '"' && i < max - 1) {
        if (*p == '\\' && p[1]) {
            p++;
            out[i++] = (*p == 'n' || *p == 't') ? ' ' : *p;
            p++;
        } else {
            out[i++] = *p++;
        }
    }
    out[i] = 0;
    while (i > 0 && out[i - 1] == ' ') out[--i] = 0; // trim trailing newline-spaces
    return i > 0;
}

// ---------- pipeline stages ----------

static int capture_frame(void) {
    // -S 3 skips the first dark/auto-exposure frames
    return system("fswebcam -r 640x480 -S 3 --jpeg 85 --no-banner " IMAGE_FILE " > /dev/null 2>&1");
}

// Send image to Gemini as base64 JSON (generateContent does not accept multipart)
static int ask_gemini(char *guidance, size_t max) {
    const char *api_key = getenv("GEMINI_API_KEY");
    if (!api_key) { printf("[Gemini] GEMINI_API_KEY not set\n"); return 0; }

    size_t img_len = 0;
    unsigned char *img = read_file(IMAGE_FILE, &img_len);
    if (!img) { printf("[Gemini] could not read %s\n", IMAGE_FILE); return 0; }
    char *b64 = base64_encode(img, img_len);
    free(img);
    if (!b64) return 0;

    size_t body_len = strlen(b64) + 2048;
    char *body = malloc(body_len);
    if (!body) { free(b64); return 0; }
    snprintf(body, body_len,
        "{\"system_instruction\":{\"parts\":[{\"text\":\"%s\"}]},"
        "\"contents\":[{\"parts\":[{\"inline_data\":{\"mime_type\":\"image/jpeg\",\"data\":\"%s\"}}]}],"
        "\"generationConfig\":{\"maxOutputTokens\":30,\"temperature\":0.2,"
        "\"thinkingConfig\":{\"thinkingBudget\":0}}}",
        SYSTEM_PROMPT, b64);
    free(b64);

    int ok = 0;
    CURL *curl = curl_easy_init();
    if (curl) {
        struct MemoryBlock chunk = { malloc(1), 0 };
        if (chunk.memory) chunk.memory[0] = 0;

        char key_header[256];
        snprintf(key_header, sizeof(key_header), "x-goog-api-key: %s", api_key);
        struct curl_slist *headers = NULL;
        headers = curl_slist_append(headers, "Content-Type: application/json");
        headers = curl_slist_append(headers, key_header);

        curl_easy_setopt(curl, CURLOPT_URL, GEMINI_URL);
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body);
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_memory_callback);
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, (void *)&chunk);
        curl_easy_setopt(curl, CURLOPT_TIMEOUT, 10L);

        CURLcode res = curl_easy_perform(curl);
        long code = 0;
        curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &code);

        if (res != CURLE_OK) {
            printf("[Gemini] request failed: %s\n", curl_easy_strerror(res));
        } else if (code != 200) {
            printf("[Gemini] HTTP %ld: %s\n", code, chunk.memory ? chunk.memory : "");
        } else if (chunk.memory && extract_gemini_text(chunk.memory, guidance, max)) {
            ok = 1;
        } else {
            printf("[Gemini] no text in response\n");
        }

        curl_slist_free_all(headers);
        curl_easy_cleanup(curl);
        free(chunk.memory);
    }
    free(body);
    return ok;
}

static void speak(const char *text) {
    const char *api_key = getenv("ELEVENLABS_API_KEY");
    if (!api_key) { printf("[Audio] ELEVENLABS_API_KEY not set\n"); return; }

    char escaped[512];
    json_escape(text, escaped, sizeof(escaped));
    char payload[768];
    snprintf(payload, sizeof(payload),
             "{\"text\":\"%s\",\"model_id\":\"eleven_flash_v2_5\"}", escaped);

    CURL *curl = curl_easy_init();
    if (!curl) return;
    FILE *fp = fopen(AUDIO_FILE, "wb");
    if (!fp) { curl_easy_cleanup(curl); return; }

    char url[256], key_header[192];
    snprintf(url, sizeof(url), "https://api.elevenlabs.io/v1/text-to-speech/%s", ELEVENLABS_VOICE_ID);
    snprintf(key_header, sizeof(key_header), "xi-api-key: %s", api_key);
    struct curl_slist *headers = NULL;
    headers = curl_slist_append(headers, "Content-Type: application/json");
    headers = curl_slist_append(headers, key_header);

    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, payload);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_audio_callback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, fp);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 10L);

    CURLcode res = curl_easy_perform(curl);
    long code = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &code);
    fclose(fp);

    if (res == CURLE_OK && code == 200) {
        system("mpg123 -q " AUDIO_FILE);
    } else {
        printf("[ElevenLabs] failed (curl: %s, HTTP %ld)\n", curl_easy_strerror(res), code);
    }
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);
}

// Append one JSON object per line (JSON Lines)
static void log_event(const char *guidance, double latency) {
    FILE *fp = fopen(LOG_FILE, "a");
    if (!fp) return;
    time_t now = time(NULL);
    struct tm *t = localtime(&now);
    char ts[64], escaped[512];
    strftime(ts, sizeof(ts), "%Y-%m-%d %H:%M:%S", t);
    json_escape(guidance, escaped, sizeof(escaped));
    fprintf(fp, "{\"timestamp\":\"%s\",\"guidance\":\"%s\",\"latency_s\":%.2f}\n", ts, escaped, latency);
    fclose(fp);
}

static double now_s(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

int main(void) {
    signal(SIGINT, on_sigint);
    signal(SIGTERM, on_sigint);
    curl_global_init(CURL_GLOBAL_ALL);
    printf("Starting VisionNav Assistant (Ctrl+C to stop)...\n");

    char last[256] = "";
    while (running) {
        double start = now_s();

        if (capture_frame() != 0) {
            printf("[Camera] capture failed\n");
        } else {
            char guidance[256];
            if (ask_gemini(guidance, sizeof(guidance))) {
                double latency = now_s() - start;
                printf("[Guidance] %s (%.2fs)\n", guidance, latency);

                // Don't nag: skip repeating "Path clear"
                int repeat_clear = strcmp(guidance, "Path clear") == 0 && strcmp(last, guidance) == 0;
                if (!repeat_clear) speak(guidance);

                log_event(guidance, latency);
                snprintf(last, sizeof(last), "%s", guidance);
            }
        }

        double elapsed = now_s() - start;
        if (elapsed < CYCLE_SECONDS) usleep((useconds_t)((CYCLE_SECONDS - elapsed) * 1e6));
    }

    curl_global_cleanup();
    printf("Stopped.\n");
    return 0;
}
