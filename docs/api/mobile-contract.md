# IMedora — Mobile API Contract (B8)

**For:** the Flutter app in `mobile/` (its `Api*` repositories replace the `Mock*` ones in `main.dart`).
**Sources:**
- Master Instructions §5, "Mobile App API Requirements";
- the app's domain models (`mobile/lib/features/*/domain`);
- team decisions of 2026-11-26.

**Checked by:** `backend/tests/test_mobile_contract.py`. That test holds the same field mapping in code and fails when the API stops matching it.

The interactive reference for every endpoint is `/docs` (OpenAPI) on a running backend.

---

## 1. Connection

| Item | Value |
|---|---|
| Base URL | `http://<host>:8000/api/v1`. The Android emulator uses `http://10.0.2.2:8000/api/v1`. **Note:** the default in `AppConfig.apiBaseUrl` lacks `/api/v1`; set it there or with `--dart-define=API_BASE_URL=…`. |
| Auth header | `Authorization: Bearer <token>` on every call except login and forgot password |
| Token | A JWT, valid 8 hours by default (`expires_in`, seconds). Treat it as opaque and store it with `SecureTokenStorage`. It stops working after a password change or reset, or when the account, its hospital or its organization is deactivated. |
| Format | JSON, `snake_case` keys. Times are ISO 8601 with an offset; dates are `YYYY-MM-DD`. UUIDs are strings. |
| Lists | Paged: `{"items": [...], "total", "page", "page_size"}`. Query parameters `page` (from 1) and `page_size` (default 20, max 100). |

## 2. Errors

Every error has one shape:

```json
{"error": {"code": "not_found", "message": "Device not found.", "details": [...]}}
```

`details` appears only for validation errors.

| HTTP | Typical `code` | App mapping |
|---|---|---|
| 401 | `unauthorized` | `AuthFailure(message)`. At login the message is always "Invalid email or password.". Elsewhere, clear the stored token and return to sign-in. |
| 403 | `forbidden`, `department_required` | `Failure(message)`. `department_required`: an administrator must assign the user a department. |
| 404 | `not_found` | `NotFoundFailure` (unknown QR code, ticket, notification…) |
| 409 / 413 / 415 | `attachment_limit_reached`, `file_too_large`, `unsupported_file`, … | `Failure(message)` |
| 422 | `validation_error`, `constraint_violation` | `Failure(message)` |
| 503 | `database_unavailable` | `NetworkFailure` |
| no response | — | `NetworkFailure` |

The `message` text is written to be shown to the user.

## 3. Calls per repository

| Repository method | Call | Notes |
|---|---|---|
| `AuthRepository.login(identifier, password)` | `POST /auth/login` `{"identifier", "password"}` | `identifier` is the **email** (no usernames, Decision 3; case-insensitive). Response `{token, user, access_token, token_type, expires_in}`: use `token` and `user`. |
| `AuthRepository.restoreSession(token)` | `GET /auth/me` | 200 returns the user; 401 means the token is no longer valid (return `null`) |
| `AuthRepository.logout()` | none | Delete the stored token. JWTs are not revoked on the server. |
| Forgot password screen | `POST /auth/forgot-password` `{"email"}` | `202 {"message"}` for every well-formed request (an empty email is 422): show `message`. No email is sent; the organization's administrators are notified in-app and give the user a new password. (An organization's only administrator cannot be helped this way.) **Suggested text change:** "Enter your email and we will send reset instructions" → "…and we will ask your administrator to reset your password". |
| `DeviceRepository.getByQrIdentifier(qr)` | `GET /devices/qr/{qr}` | Not `/devices/{qr}` (team decision). Any letter case. See §4.2 for the two response shapes. |
| `DeviceRepository.getById(id)` | `GET /devices/{id}` | `id` is the UUID |
| `DeviceRepository.listDevices()` | `GET /devices?q=…&page_size=100` | `q` matches the name, device code, serial number, QR code and **department name** |
| `TicketRepository.createTicket(req)` | `POST /tickets` `{"device_id", "category", "description", "priority"?}` | `category` is the **label** (`ProblemCategoryX.label`, e.g. `"Power issue"`); the server stores the `[label] description` prefix. Without `priority` the default is `medium`. **201** returns the ticket. Then upload photos (below). |
| photos of `NewTicketRequest.attachmentPaths` | `POST /tickets/{id}/attachments`, multipart, field **`file`**, one photo per call | JPEG/PNG; at most 3 per ticket (409); size limit `MAX_UPLOAD_MB` (413). Location and EXIF data are removed. **201** |
| `TicketRepository.getMyTickets()` | `GET /tickets/mine` | Newest first |
| `TicketRepository.getTicketsForDevice(id)` | `GET /devices/{id}/tickets` | Newest first. Department users see only the tickets they reported. |
| `TicketRepository.getTicketById(id)` | `GET /tickets/{id}` | Includes `timeline` and `attachments` |
| photo display (`TicketAttachment.fileUrl`) | `GET <file_url>` | `file_url` is an API path (`/api/v1/attachments/{id}`). Load it from the host, **with the Bearer header**, e.g. `Image.network(url, headers: …)`. |
| `NotificationRepository.getNotifications()` | `GET /notifications` | Newest first. Also returns `unread_count` for the badge. |
| `NotificationRepository.markAsRead(id)` | `PATCH /notifications/{id}/read` | Returns the notification. Another user's notification gives 404. |
| `NotificationRepository.markAllAsRead()` | `POST /notifications/read-all` | Returns `{"updated": n}` |
| `AiAssistantService.ask()` | `POST /ai/chat` | **Not available yet:** roadmap phase B9 (AI proxy). Keep the mock until then. |

## 4. Field mapping (Dart ← JSON)

### 4.1 `AuthSession` / `AuthUser`

| Dart | JSON | Notes |
|---|---|---|
| `AuthSession.token` | `token` | |
| `AuthUser.id` | `user.id` | |
| `fullName` | `user.full_name` | |
| `email` | `user.email` | |
| `hospitalName` | `user.hospital_name` | |
| `departmentName` | `user.department_name` | **May be null:** admins, engineers and technicians usually have no department, and a department user may not have one yet. The Dart field is non-nullable, so use `''` or make it nullable. |
| `role` | `user.role` | `admin`, `biomedical_engineer`, `technician` or `department_user` |

### 4.2 `Device`

| Dart | JSON | Notes |
|---|---|---|
| `id` | `id` | |
| `deviceCode` | `device_code` | |
| `name` | `name` | |
| `qrIdentifier` | `qr_identifier` | |
| `manufacturer` | `manufacturer_name` | |
| `model` | `model_name` | |
| `category` | `category_name` | |
| `department` | `department_name` | |
| `location` | `location` | nullable, `"Building - Floor - Room"` |
| `status` | `status` | `active`, `under_maintenance`, `out_of_service`, `decommissioned` |
| `criticality` | `criticality` | `low`, `medium`, `high`, `critical` |
| `installationDate` | `installation_date` | nullable date |
| `warrantyExpiry` | `warranty_expiry` | nullable date; the warranty status is computed in the app |

**QR limited view.** A department user who scans a device of **another department in the same hospital** gets `"access": "limited"`. The response has the identifying fields only:

- present: `id`, `device_code`, `name`, `qr_identifier`, `status`, the hospital and department names, `location`, `model_name`, `manufacturer_name`, `category_name`;
- absent: `criticality` and both dates.

The app may still report a problem on such a device (`POST /tickets`). It must not open the device's ticket list, which is 404 for that user.

A device in another hospital is 404.

### 4.3 `Ticket`, `TicketUpdate`, `TicketAttachment`

| Dart | JSON | Notes |
|---|---|---|
| `id` | `id` | |
| `number` | `number` | `TKT-XXXXXXXX` (Decision 4) |
| `deviceId` / `deviceName` / `deviceCode` | `device.id` / `device.name` / `device.device_code` | nested object |
| `category` | `category` | the label, already parsed from `problem_description` |
| `description` | `description` | without the `[label]` prefix |
| `priority` | `priority` | `low`, `medium`, `high`, `critical` |
| `status` | `status` | `open`, `assigned`, `in_progress`, `waiting_for_parts`, `resolved`, `closed`, `cancelled` |
| `createdAt` | `created_at` | |
| `resolvedAt` | `resolved_at` | nullable |
| `updates` | `timeline` | `GET /tickets/{id}` only, **oldest first**; each item is `{at, status, message, kind, actor?}` |
| `TicketUpdate.status` / `message` / `at` | `timeline[].status` / `.message` / `.at` | `status` is the ticket's status after the event |
| `attachments` | `attachments` | `GET /tickets/{id}` only, oldest first |
| `TicketAttachment.id` / `fileName` / `fileUrl` | `id` / `file_name` / `file_url` | `file_name` is the name sent at upload (null only if none was sent) |

Extra fields the app can ignore: `reported_by`, `assignees`, `hospital_id`, `is_deleted`, `updated_at`.

**Department users** see staff as roles, never names (decision Q9): `reported_by` and `assignees` show `{"id": null, "name": "Technician", …}`.

### 4.4 `AppNotification`

| Dart | JSON | Notes |
|---|---|---|
| `id` | `id` | |
| `type` | `type` | `ticket_created`, `ticket_assigned`, `ticket_status_changed`, `ticket_resolved`, `device_alert`. Any other value or null maps to `NotificationType.other`. Admins may also receive `password_reset_requested`. |
| `title` | `title` | |
| `body` | `body` | nullable |
| `relatedTicketId` | `related_ticket_id` | nullable. Also returned: `ticket_number`. |
| `isRead` | `is_read` | |
| `createdAt` | `created_at` | |
| `readAt` | `read_at` | nullable; never null when `is_read` is true |

## 5. Not covered by this contract

- **`POST /ai/chat`:** phase B9.
- **Push notifications:** none; notifications are in-app only (poll `GET /notifications`).
- **Settings:** theme and notification preferences stay on the device (Master Instructions §5).
- **Running the app against the API on an emulator:** done by the mobile team. The backend side of the same flow is replayed by `test_the_mobile_flow`.
