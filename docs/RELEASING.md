# Сборка и выпуск для Windows

Репозиторий содержит браузерную версию и оболочку Tauri. GitHub Actions собирает
**Pereplet-Tauri-Windows-x64.zip** и **Pereplet-Setup-Windows-x64.exe** с WebView2 Fixed Version, Python, сервером,
интерфейсом, исходниками и лицензиями. В комплект входят 12 классических книг, иллюстрированное руководство FB2 и голос «Дмитрий». Пользовательские профили и личные книги не включаются.

## Локальная сборка

Нужны Windows x64, Python 3.13 с pip, Node.js 22, Rustup, MSVC Build Tools и
Windows SDK. Версия Rust задаётся в rust-toolchain.toml. В корне проекта:

```powershell
./scripts/build-windows.ps1
python scripts/smoke_windows.py
./scripts/build-installer.ps1
python scripts/smoke_installer.py
python scripts/release_checksums.py dist
```

Результат находится в dist. Первый запуск скачивает зависимости; кэш внешних
сред находится в build/downloads. Скрипт проверяет SHA-256 загрузок и прекращает
сборку при несовпадении. При повторной сборке заменяется только build/Pereplet-Tauri-Windows-x64;
если внутри него обнаружена data, скрипт отказывается продолжать.
Для smoke-проверки закройте своё настольное приложение: используется порт 18769.
Тест распаковывает архив отдельно и не обращается к вашей библиотеке.

## Workflow без публикации

Actions → Windows distributions → Run workflow создаёт ZIP, установщик EXE и их .sha256 в Artifacts.
Push в main/master и pull request также запускают сборку и проверки.
Ручной запуск workflow, даже для тега, **не публикует Release**.

## Выпуск

1. Обновите версию в src-tauri/Cargo.toml, src-tauri/tauri.conf.json и
   frontend/package.json. Обновите Cargo.lock и frontend/package-lock.json.
2. Зафиксируйте изменения и создайте тег той же версии, например v0.1.0.
3. Отправьте этот тег на GitHub. Это запускает выпуск автоматически.
4. После успешных проверок workflow создаёт черновик Release, прикрепляет ZIP, установщик EXE
   и общий файл SHA256SUMS.txt, затем публикует его. Тег с суффиксом (например
   v0.2.0-beta.1) создаёт pre-release.

Не создавайте опубликованный Release вручную до завершения сборки. Уже
опубликованный Release workflow не перезаписывает; используйте новый тег.
Незавершённый черновик можно дополнить повторным запуском того же workflow.
Для выпуска достаточно штатного GITHUB_TOKEN: contents:write выдан только
release-job. Секреты пользователя, PAT и ключи подписи не требуются.
EXE в этом процессе не подписывается сертификатом издателя.

## Обновление зависимостей

- npm: обновите package-lock.json и выполните npm ci/check/test/build.
- Rust: обновите Cargo.lock и при необходимости rust-toolchain.toml.
- Python: requirements-portable.txt содержит полную цепочку зависимостей и
  хеши колёс для CPython 3.13 / Windows x64. Обновляйте вместе с DEPENDENCIES.json.
- Python embedded, WebView2 и GPL-исходники: build-assets/downloads.json
  содержит конкретные URL и SHA-256. При исчезновении закреплённого URL сборка
  остановится; подмены на непроверенный latest нет.
- При смене Piper обновите также соответствующие исходники Piper/eSpeak.
- build-assets/vc-runtime содержит две необходимые Microsoft VC runtime DLL;
  их условия сохранены в licenses/Microsoft-VC-runtime-license.rtf.

Встроенный WebView2 не обновляется отдельно: выпускайте новую сборку, чтобы
доставить пользователям новую версию движка. Сборка использует allowlist
исходников; data, personal, .venv, node_modules и локальные журналы не включаются.

Порядок загрузки файлов до публикации совместим с immutable releases:
https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository


## Windows installer

После сборки portable выполните `./scripts/build-installer.ps1` и `python scripts/smoke_installer.py`. Скрипт проверяет чистоту и SHA-256 файлов portable, затем создаёт `dist/Pereplet-Setup-Windows-x64.exe` с тем же содержимым. Inno Setup 6.7.4 загружается с фиксированного адреса и проверяется по SHA-256. Установщик работает без повышения прав, создаёт ярлыки и предлагает запуск приложения. Данные в data не являются частью установочного пакета и сохраняются при обновлении и удалении.

Workflow проверяет portable, установку, повторную установку и сохранность данных после удаления. В Release прикрепляются ZIP, установщик EXE и отдельные контрольные суммы. Проверки установки выполняются в одноразовом каталоге; не запускайте smoke-тест на рабочей пользовательской установке.
