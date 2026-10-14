import 'package:flutter_test/flutter_test.dart';
import 'package:opendev_timetrack/api.dart';
import 'package:opendev_timetrack/models.dart';

void main() {
  test('formats durations the way timesheets show them', () {
    expect(hm(0), '0:00');
    expect(hm(8 * 3600 + 15 * 60), '8:15');
    expect(clockText(const Duration(hours: 1, minutes: 2, seconds: 3)), '1:02:03');
  });

  test('parses a server entry and marks automatic sessions as drafts', () {
    final e = Entry.fromJson({
      'id': 1, 'start': '2026-10-13T01:00:00Z', 'end': '2026-10-13T09:30:00Z', 'break_minutes': 60,
      'location': 'office', 'source': 'phone', 'status': 'ok', 'note': '', 'running': false,
      'confirmed': false, 'worked_seconds': 27000, 'project': null,
    });
    expect(e.isDraft, isTrue);
    expect(e.sourceLabel, 'Arrived at office');
    expect(e.start.isUtc, isFalse);
  });

  test('builds dates for the API', () {
    expect(ymd(DateTime(2026, 3, 7)), '2026-03-07');
  });
}
