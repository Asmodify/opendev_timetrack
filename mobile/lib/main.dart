import 'package:flutter/material.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:intl/intl.dart';

import 'api.dart';
import 'office_watcher.dart';
import 'screens/home.dart';
import 'screens/login.dart';

const brand = Color(0xFF0E6B58);
const officeColor = Color(0xFF2F5D9E);
const remoteColor = Color(0xFFC98A12);

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting();
  // Use the phone's language for dates when intl knows it (e.g. mn, ru, en), otherwise English.
  final locale = WidgetsBinding.instance.platformDispatcher.locale.toLanguageTag();
  Intl.defaultLocale = Intl.verifiedLocale(locale, DateFormat.localeExists, onFailure: (_) => 'en');
  await Api.instance.load();
  if (Api.instance.signedIn) await OfficeWatcher.instance.restore();
  runApp(const TimeTrackApp());
}

class TimeTrackApp extends StatefulWidget {
  const TimeTrackApp({super.key});

  @override
  State<TimeTrackApp> createState() => _TimeTrackAppState();
}

class _TimeTrackAppState extends State<TimeTrackApp> {
  bool _signedIn = Api.instance.signedIn;

  void _onSignedIn() => setState(() => _signedIn = true);

  Future<void> _onSignedOut() async {
    await OfficeWatcher.instance.stop();
    await Api.instance.signOut();
    setState(() => _signedIn = false);
  }

  ThemeData _theme(Brightness b) => ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: brand, brightness: b),
        visualDensity: VisualDensity.standard,
      );

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Time Tracking',
      debugShowCheckedModeBanner: false,
      theme: _theme(Brightness.light),
      darkTheme: _theme(Brightness.dark),
      home: _signedIn
          ? HomeScreen(onSignedOut: _onSignedOut)
          : LoginScreen(onSignedIn: _onSignedIn),
    );
  }
}
