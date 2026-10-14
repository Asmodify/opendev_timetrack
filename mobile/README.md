# Time Tracking phone app

Flutter app for Android and iOS. Workers see their day as a timeline, clock in and out, tag hours with projects, confirm automatic sessions and ask for corrections. With **office check-in** on, their hours start when they arrive at an office area and stop when they leave.

## How office check-in works

- Admins draw office areas (a point and a radius) under **People → Office areas** in the dashboard.
- The phone compares its own position with those circles. It sends the server only `arrive` or `leave` and the office id, never coordinates.
- Leaving needs two readings 75 m outside the circle, so standing near the edge doesn't flicker.
- Arriving replaces an automatic remote session (for example the laptop at home) with an office session. A session the worker started by hand is left alone.
- It only runs after the worker accepts automatic tracking, and they can switch it off in **Settings**.

Background behaviour depends on the phone:

- **Android:** a "Office check-in is on" notification keeps it running in the background. The worker must choose **Allow all the time** for location.
- **iOS:** background location is enabled. The worker must choose **Always** for location.
- If the app is force-closed or the OS stops it, check-in pauses until the app is opened again. The server never counts hours it didn't hear about.

## Sessions are drafts until confirmed

This works like Timely's timeline. Automatic sessions (computer or phone) appear as **drafts**. The worker reviews their day, adds a project or note, and confirms it. Managers see how many sessions are still unconfirmed in the team timesheet. Changing times always goes through a correction request.

## Build

```bash
flutter pub get
flutter run --dart-define=SERVER_URL=https://time.your-company.mn      # bakes in the server, hides the address field
flutter build apk --release --dart-define=SERVER_URL=https://time.your-company.mn
flutter build ipa --release --dart-define=SERVER_URL=https://time.your-company.mn
```

Without `SERVER_URL` the sign-in screen asks for the server address.

- Android package id: `mn.opendev.opendev_timetrack`. Set your release signing in `android/app/build.gradle.kts`.
- iOS bundle id: `mn.opendev.opendevTimetrack`. Open `ios/Runner.xcworkspace` and choose the team.
- Store review: Google Play and the App Store ask why the app needs background location. The answer is in the location permission texts in `ios/Runner/Info.plist`: it starts work hours on arrival at the office, and only "arrived" or "left" is sent.

## Checks

```bash
flutter analyze
flutter test
```
