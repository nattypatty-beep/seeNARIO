#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
#include <curl/curl.h>

#define IMAGE_FILE "scene.jpg"
#define AUDIO_FILE "alert.mp3"
#define LOG_FILE "logs.json"
#define ELEVENLABS_VOICE_ID "21m00Tcm4TlvDq8ikWAM" // Default voice ID (Rachel)

// Buffer structure for HTTP responses
struct MemoryBlock {
    char *memory;
    size_t size;
};

// Callback to buffer incoming text data from API calls
static size_t write_memory_callback(void *contents, size_t size, size_t nmemb, void *userp) {
    size_t realsize = size * nmemb;
    struct MemoryBlock *mem = (struct MemoryBlock *)userp;
    char *ptr = realloc(mem->memory, mem->size + realsize + 1);
    if (!ptr) return 0;

    mem->memory = ptr;
    memcpy(&(mem->memory[mem->size]), contents, realsize);
    mem->size += realsize;
    mem->memory[mem->size] = 0;
    return realsize;
}

// Callback to write incoming audio stream from ElevenLabs directly to an MP3 file
static size_t write_audio_callback(void *ptr, size_t size, size_t nmemb, FILE *stream) {
    return fwrite(ptr, size, nmemb, stream);
}

// Helper: Extract text value from JSON response string without external library dependencies
void extract_gemini_text(const char *json, char *output, size_t max_len) {
    const char *key = "\"text\": \"";
    const char *start = strstr(json, key);
    if (!start) {
        snprintf(output, max_len, "Path unclear.");
        return;
    }
    start += strlen(key);

    size_t i = 0;
    while (*start != '\0' && *start != '"' && i < max_len - 1) {
        if (*start == '\\' && *(start + 1) != '\0') {
            start++; // Skip escape characters
        }
        output[i++] = *start++;
    }
    output[i] = '\0';
}

// 1 & 2. Snap Photo with Webcam
void capture_frame() {
    system("fswebcam -r 640x480 --no-banner scene.jpg > /dev/null 2>&1");
}

// 5. Synthesize and Play Audio Guidance using ElevenLabs
void play_audio_guidance(const char *text) {
    char *api_key = getenv("ELEVENLABS_API_KEY");
    if (!api_key) {
        printf("[Audio Error] ELEVENLABS_API_KEY environment variable not set.\n");
        return;
    }

    char url[256];
    snprintf(url, sizeof(url), "https://api.elevenlabs.io/v1/text-to-speech/%s", ELEVENLABS_VOICE_ID);

    char json_payload[512];
    snprintf(json_payload, sizeof(json_payload),
             "{\"text\": \"%s\", \"model_id\": \"eleven_flash_v2_5\"}", text);

    CURL *curl = curl_easy_init();
    if (curl) {
        FILE *fp = fopen(AUDIO_FILE, "wb");
        if (!fp) {
            curl_easy_cleanup(curl);
            return;
        }

        struct curl_slist *headers = NULL;
        char header_key[128];
        snprintf(header_key, sizeof(header_key), "xi-api-key: %s", api_key);

        headers = curl_slist_append(headers, "Content-Type: application/json");
        headers = curl_slist_append(headers, header_key);

        curl_easy_setopt(curl, CURLOPT_URL, url);
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json_payload);
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_audio_callback);
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, fp);

        CURLcode res = curl_easy_perform(curl);
        fclose(fp);

        if (res == CURLE_OK) {
            // Play streamed speech file over JBL speaker
            system("mpg123 -q alert.mp3");
        } else {
            printf("[ElevenLabs Error] Call failed: %s\n", curl_easy_strerror(res));
        }

        curl_slist_free_all(headers);
        curl_easy_cleanup(curl);
    }
}

// 6. Log Event to Web Dashboard (Appends structured log to JSON)
void log_event(const char *guidance_text) {
    FILE *fp = fopen(LOG_FILE, "a");
    if (!fp) return;

    time_t now = time(NULL);
    struct tm *t = localtime(&now);
    char time_str[64];
    strftime(time_str, sizeof(time_str), "%Y-%m-%d %H:%M:%S", t);

    fprintf(fp, "{\"timestamp\": \"%s\", \"guidance\": \"%s\"}\n", time_str, guidance_text);
    fclose(fp);
}

// 3 & 4. Send Photo directly to Gemini API & Analyze Hazards
void process_vision_pipeline() {
    char *api_key = getenv("GEMINI_API_KEY");
    if (!api_key) {
        printf("[Gemini Error] GEMINI_API_KEY environment variable not set.\n");
        return;
    }

    char url[256];
    snprintf(url, sizeof(url),
             "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=%s",
             api_key);

    CURL *curl = curl_easy_init();
    if (curl) {
        struct MemoryBlock chunk = {malloc(1), 0};
        curl_mime *form = curl_mime_init(curl);

        // Attach binary JPG file directly (multipart/form-data, no Base64 conversion)
        curl_mimepart *part = curl_mime_addpart(form);
        curl_mime_name(part, "file");
        curl_mime_filedata(part, IMAGE_FILE);
        curl_mime_type(part, "image/jpeg");

        // System prompt requiring short, direct navigation instructions
        part = curl_mime_addpart(form);
        curl_mime_name(part, "prompt");
        curl_mime_data(part,
            "Identify immediate hazards directly in front of the camera path and estimate if they are close. Keep output under 6 words.",
            CURL_ZERO_TERMINATED);

        curl_easy_setopt(curl, CURLOPT_URL, url);
        curl_easy_setopt(curl, CURLOPT_MIMEPOST, form);
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_memory_callback);
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, (void *)&chunk);

        CURLcode res = curl_easy_perform(curl);
        if (res == CURLE_OK) {
            char guidance[256];
            extract_gemini_text(chunk.memory, guidance, sizeof(guidance));
            
            printf("[Gemini Output]: %s\n", guidance);

            // Play voice output on JBL speaker
            play_audio_guidance(guidance);

            // Log entry for web dashboard
            log_event(guidance);
        } else {
            printf("[Gemini API Error] %s\n", curl_easy_strerror(res));
        }

        curl_mime_free(form);
        curl_easy_cleanup(curl);
        free(chunk.memory);
    }
}

int main() {
    printf("Starting VisionNav Assistant (Automated 2-3s Loop)...\n");
    curl_global_init(CURL_GLOBAL_ALL);

    while (1) {
        printf("\n--- Starting Scan Cycle ---\n");

        // Step 2: Snap Photo
        printf("[1/4] Capturing webcam frame...\n");
        capture_frame();

        // Steps 3, 4, 5 & 6: Process Image -> Gemini API -> ElevenLabs Audio -> Log
        printf("[2/4] Processing image with Gemini Vision API...\n");
        process_vision_pipeline();

        // Step 1: Automatic 2.5-second reset delay
        printf("[4/4] Resetting... Next scan in 2.5 seconds.\n");
        usleep(2500000); // 2,500,000 microseconds = 2.5 seconds
    }

    curl_global_cleanup();
    return 0;
}