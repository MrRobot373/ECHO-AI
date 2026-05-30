# Echo AI — Android App Implementation Guide

**Target:** Run Echo AI as a native Android app on an aftermarket Android car head unit, an Android tablet, or an Android phone.

> **Critical:** This guide is for **standard Android** (AOSP / aftermarket head units / Android tablets). It does NOT cover:
> - **Android Auto** — only templated media/nav/messaging apps. A full custom assistant UI is blocked by Google.
> - **Android Automotive OS (AAOS)** — requires Google partnership and car app library approval. Complex path.

---

## Deployment Path Overview

There are two paths. Choose based on your timeline:

| | Path A — WebView App | Path B — Native Android |
|---|---|---|
| **What it is** | Chromium wrapper showing the existing web UI | Full Kotlin/Java app |
| **Timeline** | 1–3 days | 4–8 weeks |
| **Actions** | Via backend (laptop/Pi/cloud) | Native Android Intents (reliable) |
| **Calls/WhatsApp** | Simulated (backend stub) | Real (Intent-based, 100% reliable) |
| **Offline** | Backend must be reachable | Fully on-device possible |
| **Skill needed** | Web + basic Android | Android SDK, Kotlin, JNI |
| **Best for** | Quick demo in car NOW | Production deployment |

**Recommendation:** Start with Path A to get it into the car this week. Then move to Path B for production.

---

## PATH A — Capacitor WebView Wrapper

### A1. Prerequisites
```bash
# Install Node.js 18+ and npm
# Install Android Studio (latest stable)
# Install JDK 17
node -v   # should be 18+
npm -v
```

### A2. Add Capacitor to the project
```bash
cd echo-ai

# Initialise a package.json if not present
npm init -y

# Install Capacitor
npm install @capacitor/core @capacitor/cli

# Initialise Capacitor
npx cap init "Echo AI" "com.getmysolutions.echoai" --web-dir frontend

# Add Android platform
npm install @capacitor/android
npx cap add android
```

### A3. Configure capacitor.config.json
```json
{
  "appId": "com.getmysolutions.echoai",
  "appName": "Echo AI",
  "webDir": "frontend",
  "server": {
    "url": "http://192.168.1.100:8123",
    "cleartext": true,
    "allowNavigation": ["192.168.1.*", "127.0.0.1", "*.open-meteo.com"]
  },
  "android": {
    "allowMixedContent": true,
    "captureInput": true,
    "webContentsDebuggingEnabled": false
  }
}
```
> Replace `192.168.1.100` with your Pi or laptop's LAN IP. Use a hotspot or car Wi-Fi router so both devices are on the same network.

### A4. Android permissions — edit `android/app/src/main/AndroidManifest.xml`
```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.RECORD_AUDIO" />
<uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS" />
<uses-permission android:name="android.permission.WAKE_LOCK" />
<uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />

<!-- For actions in Path B (add now for future) -->
<uses-permission android:name="android.permission.CALL_PHONE" />
<uses-permission android:name="android.permission.SEND_SMS" />
<uses-permission android:name="android.permission.BLUETOOTH" />
<uses-permission android:name="android.permission.CHANGE_WIFI_STATE" />
```

Activity configuration for always-on landscape kiosk:
```xml
<activity
    android:name=".MainActivity"
    android:configChanges="orientation|keyboardHidden|keyboard|screenSize|locale"
    android:screenOrientation="landscape"
    android:theme="@style/AppTheme.NoActionBar"
    android:launchMode="singleInstance"
    android:keepScreenOn="true"
    android:exported="true">
  <intent-filter>
    <action android:name="android.intent.action.MAIN" />
    <category android:name="android.intent.category.LAUNCHER" />
    <category android:name="android.intent.category.CAR_DOCK" />
  </intent-filter>
</activity>
```

### A5. Keep screen on + mic always allowed
```java
// In MainActivity.java / MainActivity.kt
@Override
protected void onCreate(Bundle savedInstanceState) {
    super.onCreate(savedInstanceState);
    getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    // Allow mic in WebView
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
        requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 1);
    }
}
```

For WebView mic access, override `onPermissionRequest`:
```java
webView.setWebChromeClient(new WebChromeClient() {
    @Override
    public void onPermissionRequest(PermissionRequest request) {
        request.grant(request.getResources());  // auto-grant in car context
    }
});
```

### A6. Build and install
```bash
# Sync web assets to Android project
npx cap sync android

# Open in Android Studio
npx cap open android

# In Android Studio:
# Build → Generate Signed APK → (create keystore)
# Install on device:
adb install app-release.apk
```

### A7. Set as default launcher (car head unit)
In Android Settings → Apps → Default Apps → Home App → select Echo AI.
Or on rooted device:
```bash
adb shell cmd package set-home-activity com.getmysolutions.echoai/.MainActivity
```

---

## PATH B — Native Android App

### Architecture
```
AndroidManifest
  └── MainActivity (full-screen, landscape, keep-screen-on)
       ├── EchoUI Fragment (RecyclerView bubbles, Canvas avatar animation)
       ├── VoiceService (Foreground Service — always-on audio pipeline)
       │    ├── OpenWakeWord / Porcupine (wake word, ONNX via onnxruntime-android)
       │    ├── SherpaOnnx (STT + VAD — single ARM-optimised library)
       │    ├── OllamaClient (HTTP to local Ollama OR embedded llama.cpp via JNI)
       │    ├── CommandRouter (Kotlin — tool calling + Intent dispatch)
       │    └── PiperTTS / Android TTS (speech synthesis)
       └── ActionExecutor (Android Intents — calls, messages, maps, apps, media)
```

### B1. Project setup
```
# Android Studio → New Project → Empty Views Activity
# Package: com.getmysolutions.echoai
# Language: Kotlin
# Min SDK: API 26 (Android 8.0) — covers 95%+ of aftermarket head units
# Target SDK: API 34
```

### B2. Key dependencies — `app/build.gradle.kts`
```kotlin
dependencies {
    // HTTP (Ollama API)
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.6.3")

    // Sherpa-ONNX (STT + VAD + TTS — single AAR, ARM64)
    // https://github.com/k2-fsa/sherpa-onnx
    implementation("com.github.k2-fsa:sherpa-onnx-android:1.10.12")

    // Porcupine wake word (alternative to OpenWakeWord)
    implementation("ai.picovoice:porcupine-android:3.0.1")

    // Audio recording
    // Uses Android's built-in AudioRecord — no extra dependency

    // Coroutines
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.0")

    // ViewModel + LiveData
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.7.0")
}
```

### B3. Avatar animation — `EchoAvatarView.kt`
```kotlin
class EchoAvatarView(context: Context) : View(context) {
    private val frames = mutableListOf<Bitmap>()
    private var currentFrame = 0
    private val handler = Handler(Looper.getMainLooper())

    fun loadFrames(state: String) {
        frames.clear()
        val assetManager = context.assets
        val folder = when(state) {
            "sleeping"   -> "avatar/normal"
            "listening"  -> "avatar/listen"
            "processing" -> "avatar/loding"
            "speaking"   -> "avatar/listen"
            "error"      -> "avatar/error"
            else         -> "avatar/normal"
        }
        assetManager.list(folder)?.forEach { filename ->
            assetManager.open("$folder/$filename").use { stream ->
                frames.add(BitmapFactory.decodeStream(stream))
            }
        }
        startAnimation()
    }

    private fun startAnimation() {
        val runnable = object : Runnable {
            override fun run() {
                currentFrame = (currentFrame + 1) % frames.size
                invalidate()
                handler.postDelayed(this, 1000L / 24)  // 24 fps
            }
        }
        handler.post(runnable)
    }

    override fun onDraw(canvas: Canvas) {
        if (frames.isNotEmpty()) {
            // Draw centred, maintain aspect ratio
            canvas.drawBitmap(frames[currentFrame], null,
                RectF(0f, 0f, width.toFloat(), height.toFloat()), null)
        }
    }
}
```

Copy frames to `app/src/main/assets/avatar/{normal,listen,loding,error}/`.

### B4. Voice pipeline — `VoiceService.kt`
```kotlin
class VoiceService : Service() {
    private lateinit var wakeWord: PorcupineManager   // or OpenWakeWord ONNX
    private lateinit var recognizer: OfflineRecognizer  // sherpa-onnx
    private lateinit var tts: OfflineTts               // sherpa-onnx Piper TTS
    private val audioRecord by lazy { buildAudioRecord() }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(NOTIFICATION_ID, buildNotification())
        startPipeline()
        return START_STICKY
    }

    private fun startPipeline() {
        CoroutineScope(Dispatchers.IO).launch {
            // 1. Listen for wake word
            // 2. On wake: switch to VAD + STT
            // 3. Send transcript to OllamaClient
            // 4. Execute tool or speak answer
        }
    }
}
```

### B5. Action executor — native Android Intents
```kotlin
object ActionExecutor {
    fun execute(tool: String, args: Map<String, Any>, context: Context): String {
        return when (tool) {
            "make_call" -> {
                val number = resolveContact(args["contact"] as String, context)
                val intent = Intent(Intent.ACTION_CALL, Uri.parse("tel:$number"))
                context.startActivity(intent)
                "Calling ${args["contact"]}."
            }
            "send_whatsapp" -> {
                val number = resolveContact(args["contact"] as String, context)
                val text = args["message"] as String
                val intent = Intent(Intent.ACTION_VIEW,
                    Uri.parse("https://wa.me/$number?text=${Uri.encode(text)}"))
                context.startActivity(intent)
                "Opening WhatsApp for ${args["contact"]}."
            }
            "navigate_maps" -> {
                val dest = args["destination"] as String
                val intent = Intent(Intent.ACTION_VIEW,
                    Uri.parse("google.navigation:q=${Uri.encode(dest)}"))
                intent.setPackage("com.google.android.apps.maps")
                context.startActivity(intent)
                "Starting navigation to $dest."
            }
            "play_spotify" -> {
                val intent = Intent(Intent.ACTION_VIEW,
                    Uri.parse("spotify:search:${args["query"]}"))
                context.startActivity(intent)
                "Playing ${args["query"]} on Spotify."
            }
            "play_youtube" -> {
                val intent = Intent(Intent.ACTION_SEARCH)
                intent.setPackage("com.google.android.youtube")
                intent.putExtra(SearchManager.QUERY, args["query"] as String)
                context.startActivity(intent)
                "Searching YouTube for ${args["query"]}."
            }
            "set_volume" -> {
                val audio = context.getSystemService(AUDIO_SERVICE) as AudioManager
                when (args["action"]) {
                    "up"   -> audio.adjustVolume(AudioManager.ADJUST_RAISE, AudioManager.FLAG_SHOW_UI)
                    "down" -> audio.adjustVolume(AudioManager.ADJUST_LOWER, AudioManager.FLAG_SHOW_UI)
                    "mute" -> audio.adjustVolume(AudioManager.ADJUST_MUTE, 0)
                }
                "Volume adjusted."
            }
            "open_app" -> {
                val name = args["name"] as String
                val pm = context.packageManager
                val packages = mapOf(
                    "calculator"  to "com.android.calculator2",
                    "maps"        to "com.google.android.apps.maps",
                    "spotify"     to "com.spotify.music",
                    "youtube"     to "com.google.android.youtube",
                    "settings"    to "com.android.settings",
                    "camera"      to "android.media.action.IMAGE_CAPTURE"
                )
                val pkg = packages[name.lowercase()]
                if (pkg != null) {
                    context.startActivity(pm.getLaunchIntentForPackage(pkg))
                    "Opening $name."
                } else "I couldn't find $name."
            }
            else -> "I'm not able to do that on this device yet."
        }
    }
}
```

### B6. On-device inference (no network required)
Use **sherpa-onnx** for the full audio pipeline:
```kotlin
// STT (Whisper tiny/small via sherpa-onnx)
val config = OfflineRecognizerConfig(
    featConfig = FeatureConfig(sampleRate = 16000, featureDim = 80),
    modelConfig = OfflineModelConfig(
        whisper = OfflineWhisperModelConfig(encoder = "encoder.int8.onnx", decoder = "decoder.int8.onnx"),
        tokens = "tokens.txt"
    )
)
val recognizer = OfflineRecognizer(config)

// TTS (Piper via sherpa-onnx)
val ttsConfig = OfflineTtsConfig(
    model = OfflineTtsModelConfig(
        vits = OfflineTtsVitsModelConfig(model = "en_US-lessac-medium.onnx", tokens = "tokens.txt", dataDir = "espeak-ng-data")
    )
)
val tts = OfflineTts(ttsConfig)
```

Download sherpa-onnx models:  
https://github.com/k2-fsa/sherpa-onnx/releases

---

## Distribution

### Sideloading (aftermarket head units)
```bash
# Enable Developer Options → USB Debugging
adb install -r echo-ai.apk
# Set as default home launcher in Android Settings
```

### APK signing for production
```bash
keytool -genkey -v -keystore echo-ai-release.jks \
  -alias echo-ai -keyalg RSA -keysize 2048 -validity 10000
# Then: Build → Generate Signed Bundle/APK in Android Studio
```

### Auto-start on boot (car ignition)
```kotlin
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            context.startActivity(
                Intent(context, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
        }
    }
}
```
Register in AndroidManifest:
```xml
<receiver android:name=".BootReceiver" android:exported="true">
    <intent-filter>
        <action android:name="android.intent.action.BOOT_COMPLETED"/>
    </intent-filter>
</receiver>
```

---

## Recommended Implementation Order

1. **Week 1** — Path A (Capacitor WebView): get it running on the head unit, test voice/commands over local Wi-Fi.
2. **Week 2** — Migrate to Path B skeleton: MainActivity + EchoAvatarView + native mic recording.
3. **Week 3** — Integrate sherpa-onnx (STT + TTS) and ActionExecutor (Intents).
4. **Week 4** — Integrate Ollama (local HTTP) or on-device llama.cpp for LLM.
5. **Week 5+** — OBD-II integration, Bluetooth HFP calls, custom wake word.
