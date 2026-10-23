import 'package:flutter/material.dart';

const violet = Color(0xFF6C2BD9);
const violetDark = Color(0xFF4F1AAE);
const violetSoft = Color(0xFFF1EAFE);
const ink = Color(0xFF1B1230);
const muted = Color(0xFF6E6785);
const bg = Color(0xFFF5F2FA);
const line = Color(0xFFE7E1F1);
const green = Color(0xFF17B26A);
const greenSoft = Color(0xFFE3F6EC);
const yellow = Color(0xFFFFD60A);
const dark = Color(0xFF171024);
const red = Color(0xFFD92D20);
const orange = Color(0xFFB45309); // aclaraciones para la cocina y tickets en espera

ThemeData trappiTheme() {
  final base = ThemeData(
    useMaterial3: true,
    colorScheme: ColorScheme.fromSeed(seedColor: violet, primary: violet, surface: Colors.white),
    scaffoldBackgroundColor: bg,
    fontFamily: 'Segoe UI',
  );
  return base.copyWith(
    textTheme: base.textTheme.apply(bodyColor: ink, displayColor: ink),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: line)),
      enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: line)),
      focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: violet, width: 2)),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: violet,
        padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 18),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: ink,
        side: const BorderSide(color: line),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
    ),
    dialogTheme: DialogThemeData(backgroundColor: Colors.white, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18))),
  );
}
