// VisionNav Assistant - Raspberry Pi
// Build: gcc main.c -o visionnav -lcurl

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
    return
