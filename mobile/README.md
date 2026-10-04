# IMedora Mobile (Flutter)

Companion app for hospital staff (doctors, nurses...). Scan a device QR code,
see basic device info, report a problem, follow tickets, read notifications,
and ask a simple AI assistant. Technical/biomedical features live in the web app.

**Status:** MVP running on **mock data**. It never talks to PostgreSQL; once the
backend exists it will only use the REST API.

## Run

```bash
cd mobile
flutter pub get
flutter run -d <android-emulator-or-device>
```

Demo login: `demo@imedora.local` / `Demo123!`
Demo QR codes (type them in the Scan screen): `IMEDORA-DEV-001`, `IMEDORA-DEV-002`, `IMEDORA-DEV-003`
(the real `devices.qr_identifier` values such as `QR-CMC-DEV-001` work too).
In the AI chat, type `test error` to see the error state.

```bash
flutter analyze
flutter test
```

## Structure

```
lib/
  main.dart            composition root: the ONLY place choosing Mock vs real API
  app.dart             MaterialApp, providers, theme
  core/                constants, theme, routing, errors, storage, utils, shared widgets
  features/<name>/
    domain/            entities + abstract repositories/services
    data/              Mock* implementations (later Api* implementations)
    presentation/      screens, widgets, controllers
```

Features: auth, home, devices, qr_scanner, tickets, notifications,
ai_assistant, profile (+ settings).

## Connecting the backend later

1. Add an `ApiClient` in `core/network/` (base URL from `AppConfig.apiBaseUrl`;
   Android emulator reaches the host at `10.0.2.2`).
2. Write `ApiAuthRepository`, `ApiDeviceRepository`, `ApiTicketRepository`,
   `ApiNotificationRepository`, `BackendAiAssistantService` implementing the
   same interfaces as the mocks.
3. Swap them in `main.dart`. Screens do not change.

Expected endpoints: `POST /auth/login`, `GET /devices/{qr_identifier}`,
`POST /tickets`, `GET /tickets/mine`, `GET /notifications`,
`PATCH /notifications/{id}/read`, `POST /ai/chat`.

Database notes handled in the app (schema is frozen): the problem category is
stored as a prefix of `problem_description`; ticket history comes from the
backend (audit logs / assignments); warranty status is computed from
`warranty_expiry`.

## Android build notes

- `minSdk` must be 23+ (flutter_secure_storage); NDK is installed through Android Studio's SDK Manager.
- Keep the project and the Pub cache on the SAME drive, or set
  `kotlin.incremental=false` in `android/gradle.properties` (Kotlin cannot
  compute relative paths across drives).
- Free several GB of disk space before the first build.
