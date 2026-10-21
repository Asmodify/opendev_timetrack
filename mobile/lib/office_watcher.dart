import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:geolocator/geolocator.dart';

import 'api.dart';
import 'models.dart';

/// Watches the phone's position and tells the server when the worker
/// arrives at or leaves an office area. Coordinates never leave the phone;
/// only "arrive" or "leave" plus the office id are sent.
class OfficeWatcher {
  OfficeWatcher._();
  static final OfficeWatcher instance = OfficeWatcher._();

  static const _storage = FlutterSecureStorage();
  static const _leaveMarginM = 75.0; // extra distance before counting as "left", so the edge doesn't flicker
  static const _leaveReadings = 2;

  final status = ValueNotifier<String>('Off');
  final enabled = ValueNotifier<bool>(false);

  StreamSubscription<Position>? _sub;
  List<Office> _offices = [];
  int? _insideOfficeId;
  int _outsideCount = 0;

  Future<void> restore() async {
    if (await _storage.read(key: 'auto_office') == 'on') {
      final error = await start();
      if (error != null) status.value = error;
    }
  }

  /// Returns a message to show the worker when tracking can't start.
  Future<String?> start() async {
    if (!await Geolocator.isLocationServiceEnabled()) {
      return 'Turn on Location Services to check in automatically.';
    }
    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) permission = await Geolocator.requestPermission();
    if (permission == LocationPermission.denied || permission == LocationPermission.deniedForever) {
      return 'Allow location access in Settings to check in automatically.';
    }
    try {
      _offices = await Api.instance.offices();
    } on ApiError catch (e) {
      return e.message;
    }
    if (_offices.isEmpty) return 'No office areas are set up yet. Ask an admin to add one.';

    await _sub?.cancel();
    _sub = Geolocator.getPositionStream(locationSettings: _settings()).listen(_onPosition,
        onError: (Object e) => status.value = 'Location paused: $e');
    enabled.value = true;
    await _storage.write(key: 'auto_office', value: 'on');
    status.value = permission == LocationPermission.always
        ? 'Watching for ${_offices.map((o) => o.name).join(', ')}'
        : 'Works while the app is open. Choose "Allow all the time" in Settings to check in in the background.';
    return null;
  }

  Future<void> stop() async {
    await _sub?.cancel();
    _sub = null;
    enabled.value = false;
    _insideOfficeId = null;
    status.value = 'Off';
    await _storage.write(key: 'auto_office', value: 'off');
  }

  LocationSettings _settings() {
    if (defaultTargetPlatform == TargetPlatform.android) {
      return AndroidSettings(
        accuracy: LocationAccuracy.medium,
        distanceFilter: 30,
        intervalDuration: const Duration(minutes: 1),
        foregroundNotificationConfig: const ForegroundNotificationConfig(
          notificationTitle: 'Office check-in is on',
          notificationText: 'Your hours start when you arrive at the office.',
          notificationChannelName: 'Office check-in',
          enableWakeLock: false,
          setOngoing: true,
        ),
      );
    }
    if (defaultTargetPlatform == TargetPlatform.iOS) {
      return AppleSettings(
        accuracy: LocationAccuracy.medium,
        distanceFilter: 30,
        activityType: ActivityType.other,
        pauseLocationUpdatesAutomatically: true,
        allowBackgroundLocationUpdates: true,
        showBackgroundLocationIndicator: false,
      );
    }
    return const LocationSettings(accuracy: LocationAccuracy.medium, distanceFilter: 30);
  }

  Future<void> _onPosition(Position p) async {
    Office? nearest;
    var nearestDistance = double.infinity;
    for (final o in _offices) {
      final d = Geolocator.distanceBetween(p.latitude, p.longitude, o.latitude, o.longitude);
      if (d < nearestDistance) {
        nearest = o;
        nearestDistance = d;
      }
    }
    if (nearest == null) return;
    final inside = nearestDistance <= nearest.radiusM && p.accuracy <= nearest.radiusM * 1.5;

    if (inside && _insideOfficeId != nearest.id) {
      _insideOfficeId = nearest.id;
      _outsideCount = 0;
      await _report('arrive', nearest);
    } else if (_insideOfficeId != null) {
      final current = _offices.firstWhere((o) => o.id == _insideOfficeId, orElse: () => nearest!);
      final d = Geolocator.distanceBetween(p.latitude, p.longitude, current.latitude, current.longitude);
      if (d > current.radiusM + _leaveMarginM) {
        _outsideCount++;
        if (_outsideCount >= _leaveReadings) {
          _insideOfficeId = null;
          _outsideCount = 0;
          await _report('leave', current);
        }
      } else {
        _outsideCount = 0;
      }
    }
  }

  Future<void> _report(String event, Office office) async {
    try {
      final r = await Api.instance.presence(event, office.id);
      final now = DateTime.now();
      final when = '${now.hour}:${now.minute.toString().padLeft(2, '0')}';
      status.value = switch (r['state']) {
        'working' => 'At ${office.name} since $when',
        'stopped' => 'Left ${office.name}. Hours stopped.',
        'manual' => 'At ${office.name}. You clocked in by hand, so that session continues.',
        _ => 'Watching for ${_offices.map((o) => o.name).join(', ')}',
      };
    } on ApiError catch (e) {
      status.value = e.message;
    }
  }
}
