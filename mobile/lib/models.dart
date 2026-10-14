import 'package:flutter/material.dart';

DateTime? _time(Object? iso) => iso == null ? null : DateTime.parse(iso as String).toLocal();

Color hexColor(String hex) => Color(int.parse(hex.substring(1), radix: 16) | 0xFF000000);

class User {
  User.fromJson(Map<String, dynamic> j)
      : id = j['id'] as int,
        name = j['name'] as String,
        email = j['email'] as String,
        role = j['role'] as String,
        consent = j['consent'] as bool,
        mustChangePassword = j['must_change_password'] as bool,
        weeklyTargetHours = (j['weekly_target_hours'] as num).toDouble();
  final int id;
  final String name, email, role;
  final bool consent, mustChangePassword;
  final double weeklyTargetHours;
}

class Project {
  Project.fromJson(Map<String, dynamic> j)
      : id = j['id'] as int,
        name = j['name'] as String,
        client = j['client'] as String?,
        color = hexColor(j['color'] as String);
  final int id;
  final String name;
  final String? client;
  final Color color;
}

class Office {
  Office.fromJson(Map<String, dynamic> j)
      : id = j['id'] as int,
        name = j['name'] as String,
        latitude = (j['latitude'] as num).toDouble(),
        longitude = (j['longitude'] as num).toDouble(),
        radiusM = j['radius_m'] as int;
  final int id;
  final String name;
  final double latitude, longitude;
  final int radiusM;
}

class Entry {
  Entry.fromJson(Map<String, dynamic> j)
      : id = j['id'] as int,
        start = _time(j['start'])!,
        end = _time(j['end']),
        breakMinutes = j['break_minutes'] as int,
        location = j['location'] as String,
        source = j['source'] as String,
        status = j['status'] as String,
        note = j['note'] as String,
        running = j['running'] as bool,
        confirmed = j['confirmed'] as bool,
        workedSeconds = j['worked_seconds'] as int,
        project = j['project'] == null ? null : Project.fromJson(j['project'] as Map<String, dynamic>);
  final int id;
  final DateTime start;
  final DateTime? end;
  final int breakMinutes, workedSeconds;
  final String location, source, status, note;
  final bool running, confirmed;
  final Project? project;

  bool get automatic => source == 'agent' || source == 'phone';
  bool get isDraft => automatic && !confirmed && !running;
  String get sourceLabel => const {
        'agent': 'Computer',
        'phone': 'Arrived at office',
        'web': 'Clock button',
        'manual': 'Correction',
      }[source] ??
      source;
}

class Me {
  Me.fromJson(Map<String, dynamic> j)
      : user = User.fromJson(j['user'] as Map<String, dynamic>),
        company = j['company'] as String,
        here = j['here'] as String,
        running = j['running'] == null ? null : Entry.fromJson(j['running'] as Map<String, dynamic>);
  final User user;
  final String company, here;
  final Entry? running;
}

class DayTotal {
  DayTotal.fromJson(Map<String, dynamic> j)
      : date = DateTime.parse(j['date'] as String),
        office = j['office'] as int,
        remote = j['remote'] as int;
  final DateTime date;
  final int office, remote;
  int get total => office + remote;
}

class Summary {
  Summary.fromJson(Map<String, dynamic> j)
      : today = j['today'] as int,
        week = j['week'] as int,
        month = j['month'] as int,
        weeklyTargetHours = (j['weekly_target_hours'] as num).toDouble(),
        days = [for (final d in j['week_days'] as List) DayTotal.fromJson(d as Map<String, dynamic>)];
  final int today, week, month;
  final double weeklyTargetHours;
  final List<DayTotal> days;
}

String hm(int seconds) {
  final m = (seconds / 60).round();
  return '${m ~/ 60}:${(m % 60).toString().padLeft(2, '0')}';
}

String clockText(Duration d) {
  final s = d.inSeconds < 0 ? 0 : d.inSeconds;
  return '${s ~/ 3600}:${(s ~/ 60 % 60).toString().padLeft(2, '0')}:${(s % 60).toString().padLeft(2, '0')}';
}
