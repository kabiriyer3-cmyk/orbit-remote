# Гайд для ИИ-ассистентов

Этот файл читают ИИ-ассистенты (Claude, Codex, Cursor и другие) перед правками в Orbit. Здесь карта проекта, правила и проверки. Если меняете устройство проекта, обновите и этот файл.

## ⚠️ Правило для каждого коммита

Каждый коммит, сделанный с помощью ИИ, заканчивается строкой соавтора Claude. Перед ней пустая строка:

```text
Короткое описание изменения

Подробности, если нужны.

Co-authored-by: Claude <noreply@anthropic.com>
```

- Строка пишется ровно так, последней в сообщении коммита. Тогда GitHub показывает Claude соавтором.
- Не забывайте её при `git commit --amend`, squash и в коммитах слияния PR.
- Перед `git push` проверьте: `git log -1 --format='%(trailers:key=Co-authored-by)'` должен вывести строку с Claude.

## Что это

Orbit управляет Windows-компьютером с Android-телефона в одной Wi‑Fi сети: экран, мышь, клавиатура, звук. Нет аккаунтов, облака и телеметрии. Компьютерная часть написана на Python и собирается в один `Orbit.exe`. Телефонная часть написана на обычном JavaScript без сборщика и работает внутри Capacitor (Android WebView).

## Карта проекта

| Путь | Что там |
|---|---|
| `host/orbit_host/main.py` | Точка входа, аргументы (`--demo`, `--headless`, `--selftest`, `--minimized`, `--port`, `--data-dir`), запуск и завершение |
| `host/orbit_host/core.py` | Общее состояние: код сессии, сессии, запросы на подключение, доверенные телефоны, журнал, действия панели (`handle_action`), настройки, UAC |
| `host/orbit_host/session.py` | Одно подключение телефона: вход, поток кадров, ввод, звук |
| `host/orbit_host/server.py` | aiohttp: порт для телефона (TLS, 47800) и панель на `127.0.0.1` со случайным портом и токеном |
| `host/orbit_host/secure.py` | Ключ компьютера, TLS-сертификат, сквозное шифрование, доказательство кода |
| `host/orbit_host/capture.py` | Захват экрана (mss), JPEG-кадры, номера типов сообщений |
| `host/orbit_host/audio.py` | `AudioHub`: запись звука WASAPI loopback (`soundcard`), раздача слушающим сессиям, тестовый тон |
| `host/orbit_host/inputs/` | Ввод: `windows.py` (SendInput), `dummy.py` (заглушка для `--demo`), `keys.py` (названия клавиш и коды VK) |
| `host/orbit_host/winutil.py` | Windows: DPI, права администратора, брандмауэр, автозапуск, MSIX, политика UAC |
| `host/orbit_host/config.py` | `config.json` в `%APPDATA%\OrbitRemote`: `DEFAULTS`, доверенные телефоны |
| `host/orbit_host/discovery.py` | Ответы на поиск по UDP 47801 (`ORBIT_DISCOVER_V1`) |
| `host/orbit_host/ui_window.py` | Окно pywebview и иконка в трее |
| `host/orbit_host/web/` | Панель на ПК: `host.html`, `js/host.js`, `css/host.css` |
| `host/orbit_host/selftest.py`, `testclient.py` | Самотест и Python-клиент протокола, которые запускает CI |
| `host/orbit.spec`, `requirements.txt`, `version_info.txt` | Сборка PyInstaller, зависимости, метаданные exe |
| `client/index.html`, `client/css/app.css` | Интерфейс телефона |
| `client/js/app.js` | Экраны, листы, кнопки сессии, `VERSION` |
| `client/js/session.js` | `OrbitSession`: подключение, рукопожатие, разбор сообщений, отправка ввода |
| `client/js/crypto.js` | Рукопожатие и шифрование на WebCrypto |
| `client/js/viewer.js` | Canvas: кадры, масштаб, курсор |
| `client/js/input.js` | Жесты (тачпад и касание), клавиатура, модификаторы |
| `client/js/audio.js` | `player`: воспроизведение PCM через Web Audio |
| `client/js/native.js` | Мост к Android-плагину; в браузере его вызовы ничего не делают |
| `client/js/icons.js`, `ui.js`, `store.js` | Иконки, нижние листы и уведомления, localStorage |
| `mobile/android/.../MainActivity.java` | Настройки WebView, отступы, полноэкранный режим |
| `mobile/android/.../OrbitNativePlugin.java`, `PinnedTunnel.java` | Нативный TLS-туннель с проверкой ключа ПК, поиск в сети, вибрация |
| `packaging/msix/` | Пакет для Microsoft Store |
| `.github/workflows/build.yml` | CI: сборка exe и apk, самотесты, релиз по тегу `v*` |
| `.github/scripts/stamp_version.py` | Записывает версию в `__init__.py` и `version_info.txt` |
| `docs/privacy.md`, `docs/publishing.md` | Политика конфиденциальности, публикация и подпись |

## Протокол

1. Телефон подключается по `wss://ПК:47800/ws`. Сертификат самоподписанный, а телефон запоминает отпечаток ключа, тот же «ключ безопасности», что показан на экранах.
2. Первое текстовое сообщение — рукопожатие: ECDH P-256, HKDF-SHA256, ключи `orbit/1 c2h` и `orbit/1 h2c`. Ключ рукопожатия обязан совпадать с ключом TLS.
3. Дальше идут только бинарные сообщения AES-256-GCM. Первый байт открытого текста — тип:

| Байт | Тип | Содержимое |
|---|---|---|
| `0x01` | `MSG_JSON` | UTF-8 JSON с полем `t` |
| `0x02` | `MSG_FRAME` | `<IHHff>` (seq, w, h, cursor x, cursor y), затем JPEG |
| `0x03` | `MSG_AUDIO` | `<IBBH>` (rate, channels, bits=16, seq), затем PCM int16 LE, 960 сэмплов на канал |

JSON от телефона: `auth`, `ack`, `ping`, `cfg`, `mon`, `pause`, `resume`, `audio` (`on`), `bye` и ввод: `move`, `rel`, `btn`, `wheel`, `key`, `combo`, `text`, `sys`.
JSON от ПК: `auth` (`ok`, `token`, `session`), `pending`, `pong`, `cur`, `mon`, `control`, `audio` (`on`, `reason`), `bye`.

Новый тип сообщения добавляйте сразу в четыре места: `session.py`, `client/js/session.js`, `testclient.py` и проверку в `selftest.py`.

## Панель на ПК

`host.js` вызывает `POST /api/host/action` с заголовком `X-Orbit-Token`, состояние приходит из `core.snapshot()` через `/api/host/ws`.
Действия: `regenerate_code`, `approve`, `decline`, `disconnect`, `disconnect_all`, `view_only`, `revoke`, `settings`, `autostart`, `startup_settings`, `firewall`, `elevate`, `show`, `clear_activity`.
Настройки (camelCase в панели, snake_case в `config.json`): `requireApproval`, `allowInput`, `allowAudio`, `showUacPrompts`, `quality`, `fps`, `maxWidth`, `deviceName`.
Новую настройку добавьте в `DEFAULTS`, `core.snapshot()`, `core._apply_settings()`, `host.html` и `renderSettings()` в `host.js`.

## Запуск и проверка

```bash
cd host
python -m venv .venv && . .venv/bin/activate      # на Windows: .venv\Scripts\activate
pip install -r requirements.txt                    # на Linux достаточно aiohttp cryptography mss Pillow numpy
python run_orbit.py --demo --headless              # тестовый экран, без реального ввода; работает на Linux и macOS
python run_orbit.py --selftest result.json --demo  # самотест: захват, ввод, протокол, звук
```

- Клиент телефона можно открыть в браузере: `python -m http.server` в `client/`. Шифрование требует localhost или https.
- `node --check client/js/*.js` проверяет синтаксис. Сборщика и тестов JS нет.
- Android: `cd mobile && npm ci && npx cap sync android && cd android && ./gradlew assembleRelease` (Node 22, JDK 21, Android SDK 36).
- Что нельзя проверить без настоящего Windows ПК (ввод в окна, WASAPI, UAC), проверяет CI на `windows-latest` в каждом PR. После пуша смотрите `gh run list` и `gh run view`.

## Правила

- **Безопасность.** Не ослабляйте проверку ключа, сквозное шифрование, одноразовый код, блокировку после неверных попыток и подтверждение на ПК. Панель доступна только с `127.0.0.1` и только с токеном.
- **Конфиденциальность.** Без телеметрии, аналитики и внешних серверов. Если появляются новые данные (например, звук), обновите `docs/privacy.md`.
- **Настройки Windows.** Всё, что меняет систему (UAC, брандмауэр, автозапуск), включается только явно, сохраняет прежнее значение и возвращает его (см. `uac_restore` в `core.py`).
- **Честность в интерфейсе.** Не обещайте того, что Windows не даёт сделать. Нажать в окне UAC нельзя: `consent.exe` работает с уровнем целостности System. Ограничения описывайте в README.
- **Потоки.** aiohttp живёт в своём event loop. Код из других потоков (захват, звук, трей) передаёт работу через `loop.call_soon_threadsafe` или `asyncio.run_coroutine_threadsafe` и никогда не блокирует loop.
- **Стиль.** Python 3.12 с type hints и `from __future__ import annotations`. JS: ES-модули, без зависимостей и сборщика. Иконки берутся из `icons.js` (SVG 24×24, обводка 1.75). Текст интерфейса на английском, README на русском, плюс раздел English.
- **Зависимости.** Новую Python-библиотеку добавьте в `requirements.txt` и, если нужно, в `hiddenimports` и `datas` в `orbit.spec`. Проверьте, что CI собрал exe и самотест упакованного exe прошёл.
- **Документация.** Новую функцию опишите в README: русский раздел, «Ограничения» и English.

## Версии и релиз

Версию поднимайте везде сразу: `host/orbit_host/__init__.py`, `host/version_info.txt` (`python .github/scripts/stamp_version.py X.Y.Z` из `host/`), `VERSION` в `client/js/app.js`, `mobile/package.json` и `mobile/package-lock.json`.
Релиз публикует CI, когда появляется тег `vX.Y.Z` на `main`. Текст релиза лежит в `.github/release-notes.md`.

## Перед коммитом

- [ ] Самотест `--selftest --demo` проходит
- [ ] `node --check` проходит для изменённых JS-файлов
- [ ] README, `docs/privacy.md` и этот файл обновлены, если изменилось поведение или устройство проекта
- [ ] Последняя строка сообщения: `Co-authored-by: Claude <noreply@anthropic.com>`
