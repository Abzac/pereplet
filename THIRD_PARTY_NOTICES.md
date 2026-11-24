# Third-party components and assets

The root GPLv3 license covers original project source. It does not replace the
licenses below or licenses of separately installed dependencies.

- **UnRAR64.dll**: Copyright Alexander Roshal. Original freeware license is
  included in `vendor/unrar/license.txt`; source URL and SHA-256 are documented
  in `vendor/unrar/README.md`. Windows x64 only.
- **Literata, PT Serif, Source Serif 4, Inter**: SIL Open Font License 1.1.
  Original notices are retained in `frontend/public/assets/fonts/*-OFL.txt`.
- **Phosphor Icons**: MIT, Copyright (c) 2020 Phosphor Icons. License retained in
  `licenses/phosphor-MIT.txt`; installed through npm, not bundled as node_modules.
- **Piper**: optional external runtime `piper-tts`, GPL-3.0-or-later, from
  https://github.com/OHF-Voice/piper1-gpl. It and its models are not included in
  this source archive. Model sources, revisions, hashes and model-card URLs
  are listed in `model-manifest.json`; each model has its own terms.
- Python and npm dependencies are installed separately. Preserve their licenses
  if preparing a binary distribution; this archive is a source distribution.
- Paper, cloth, wood and fallback-cover textures were generated with ImageGen
  for this project. They are not extracted from user books. The original project
  grants reuse under the root GPLv3 terms to the extent of applicable rights.
- Demonstration text and CBR test fixtures are original synthetic examples.
  Fixture passwords are public test strings, not user credentials.
- `app-icon.ico` is a simple original book drawing generated for this project.


## Desktop portable (Tauri)

Оболочка Tauri и Rust-библиотеки перечисляются в TAURI-DEPENDENCIES.json
готового ZIP; полные лицензии сохраняются в licenses/rust. Python и зависимости
перечислены в DEPENDENCIES.json, их лицензии остаются в runtime/packages.
Исходники Piper и eSpeak NG соответствующих версий включаются в third-party-source.
Microsoft WebView2 Fixed Runtime: licenses/Microsoft-WebView2-Fixed.LICENSE.
Microsoft Visual C++ runtime: licenses/Microsoft-VC-runtime-license.rtf.
GPLv3 проекта не заменяет самостоятельные условия этих компонентов.

## Release audit additions

Frontend dependency notices and metadata are retained in licenses/npm and
NPM-DEPENDENCIES.json in binary packages. Missing upstream notices and their
provenance are documented in licenses/supplemental and docs/LICENSE_AUDIT.md.
Corresponding MPL crate sources accompany Piper/eSpeak sources in third-party-source.
The bundled Dmitri revision and training-chain attribution are documented in
licenses/VOICE_ATTRIBUTION.md; model weights are not relicensed under GPLv3.
See docs/LICENSE_AUDIT.md for unresolved distribution questions.

The original Pereplet code carries the narrowly scoped additional permission
in LICENSE-EXCEPTIONS.md under GPLv3 section 7. Third-party licenses are unchanged.
