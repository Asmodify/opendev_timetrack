import 'dart:convert';

import 'package:flutter/foundation.dart' show defaultTargetPlatform, TargetPlatform;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

import 'models.dart';

class ApiError implements Exception {
  ApiError(this.status, this.message);
  final int status;
  final String message;
  @override
  String toString() => message;
}

/// Talks to the time-tracking server.
///
/// After signing in, the app registers itself as a phone and keeps that
/// long-lived device token in secure storage, so background office
/// arrivals keep working without the worker signing in again.
class Api {
  Api._();
  static final Api instance = Api._();

  static const _storage = FlutterSecureStorage();
  static const defaultServer = String.fromEnvironment('SERVER_URL', defaultValue: '');

  String server = '';
  String? _token;

  bool get signedIn => _token != null && server.isNotEmpty;

  Future<void> load() async {
    server = await _storage.read(key: 'server') ?? defaultServer;
    _token = await _storage.read(key: 'token');
  }

  Future<void> signIn(String serverUrl, String email, String password) async {
    server = serverUrl.trim().replaceAll(RegExp(r'/+$'), '');
    final login = await _request('POST', '/api/auth/login', {'email': email.trim(), 'password': password}, auth: false);
    _token = login['token'] as String;
    final platform = defaultTargetPlatform;
    final name = platform == TargetPlatform.iOS ? 'iPhone' : 'Android phone';
    final phone = await _send('POST', '/api/me/phone', {'device_name': name, 'platform': platform.name});
    _token = phone['token'] as String;
    await _storage.write(key: 'server', value: server);
    await _storage.write(key: 'token', value: _token);
  }

  Future<void> signOut() async {
    _token = null;
    await _storage.delete(key: 'token');
  }

  Future<dynamic> _send(String method, String path, [Object? body]) => _request(method, path, body);

  Future<dynamic> _request(String method, String path, Object? body, {bool auth = true}) async {
    final uri = Uri.parse('$server$path');
    final headers = {
      'Content-Type': 'application/json',
      if (auth && _token != null) 'Authorization': 'Bearer $_token',
    };
    late http.Response res;
    try {
      final payload = body == null ? null : jsonEncode(body);
      final Future<http.Response> call = switch (method) {
        'GET' => http.get(uri, headers: headers),
        'POST' => http.post(uri, headers: headers, body: payload ?? '{}'),
        'PATCH' => http.patch(uri, headers: headers, body: payload),
        'DELETE' => http.delete(uri, headers: headers),
        _ => throw ArgumentError(method),
      };
      res = await call.timeout(const Duration(seconds: 20));
    } on ArgumentError {
      rethrow;
    } catch (_) {
      throw ApiError(0, "Can't reach the server. Check your internet connection.");
    }
    final text = utf8.decode(res.bodyBytes);
    if (res.statusCode >= 400) {
      var message = 'Something went wrong (${res.statusCode}).';
      try {
        final detail = jsonDecode(text)['detail'];
        if (detail is String) message = detail;
      } catch (_) {}
      if (res.statusCode == 401 && auth) await signOut();
      throw ApiError(res.statusCode, message);
    }
    return text.isEmpty ? null : jsonDecode(text);
  }

  // ---------- worker endpoints ----------
  Future<Me> me() async => Me.fromJson(await _send('GET', '/api/me'));
  Future<Summary> summary() async => Summary.fromJson(await _send('GET', '/api/me/summary'));
  Future<List<Project>> projects() async =>
      [for (final p in await _send('GET', '/api/me/projects') as List) Project.fromJson(p)];
  Future<List<Office>> offices() async =>
      [for (final o in await _send('GET', '/api/me/offices') as List) Office.fromJson(o)];

  Future<List<Entry>> entries(DateTime from, DateTime to) async {
    final rows = await _send('GET', '/api/me/entries?start=${ymd(from)}&end=${ymd(to)}') as List;
    return [for (final e in rows) Entry.fromJson(e)];
  }

  Future<void> clockIn({String note = '', int? projectId}) =>
      _send('POST', '/api/me/clock-in', {'note': note, 'project_id': projectId});
  Future<void> clockOut() => _send('POST', '/api/me/clock-out');

  Future<Entry> updateEntry(int id, {int? projectId, bool clearProject = false, String? note, bool? confirmed}) async =>
      Entry.fromJson(await _send('PATCH', '/api/me/entries/$id', {
        'project_id': projectId,
        'clear_project': clearProject,
        'note': note,
        'confirmed': confirmed,
      }));

  Future<int> confirmDay(DateTime day) async =>
      (await _send('POST', '/api/me/confirm-day', {'date': ymd(day)}))['confirmed'] as int;

  Future<void> setConsent(bool accept) => _send('POST', '/api/me/consent', {'accept': accept});

  Future<void> changePassword(String current, String next) =>
      _send('POST', '/api/auth/change-password', {'current_password': current, 'new_password': next});

  Future<void> requestCorrection(Map<String, Object?> body) => _send('POST', '/api/me/corrections', body);

  Future<Map<String, dynamic>> presence(String event, int officeId) async =>
      Map<String, dynamic>.from(await _send('POST', '/api/agent/presence', {'event': event, 'office_id': officeId}));
}

String ymd(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
