# Подпись и публикация в магазинах

Здесь описано, как убрать предупреждения Windows и Android при установке Orbit. Всё, что можно было сделать в коде и в GitHub Actions, уже сделано. Остальное требует аккаунта разработчика на ваше имя, поэтому выполняется вручную, один раз.

| Что сделать | Цена | Результат |
|---|---|---|
| Выложить MSIX в Microsoft Store | бесплатно для частного разработчика | установка из Store без SmartScreen |
| Подписать `.exe` через SignPath Foundation | бесплатно для open source | у файла появляется издатель, предупреждение со временем пропадает |
| Купить сертификат подписи кода | от 150 долларов в год | то же, что SignPath, но издатель вы |
| Зарегистрировать приложение в Android Developer Console | бесплатно | APK можно ставить там, где Google требует проверку разработчика |
| Выложить AAB в Google Play | 25 долларов один раз | установка из Play без запросов про неизвестные источники |

## Microsoft Store

Store сам подписывает пакет своим сертификатом, поэтому SmartScreen на такую установку не реагирует. Сборка MSIX уже есть в CI: при каждом теге `v*` workflow кладёт `Orbit-Windows-Store.msix` в артефакт `store-windows-msix` и проверяет, что пакет ставится и запускается на чистой Windows.

1. Зарегистрируйтесь как частный разработчик на [storedeveloper.microsoft.com](https://storedeveloper.microsoft.com). Для частных лиц регистрация бесплатная, нужен документ и селфи для проверки личности.
2. В [Partner Center](https://partner.microsoft.com/dashboard) создайте приложение и зарезервируйте имя, например «Orbit Remote».
3. Откройте Product management → Product identity. Там будут три значения: Package/Identity/Name, Package/Identity/Publisher и Package/Properties/PublisherDisplayName.
4. Сохраните их в переменные репозитория:

   ```bash
   gh variable set MSIX_IDENTITY_NAME --body "12345YourName.OrbitRemote"
   gh variable set MSIX_PUBLISHER --body "CN=XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
   gh variable set MSIX_PUBLISHER_DISPLAY_NAME --body "Your Name"
   ```

5. Выпустите новую версию (`git tag v1.1.1 && git push origin v1.1.1`), дождитесь сборки и скачайте артефакт `store-windows-msix` со страницы запуска в Actions.
6. В Partner Center создайте Submission, в разделе Packages загрузите `.msix`.
7. Заполните оставшиеся разделы. Что спросят и что ответить:
   - Политика конфиденциальности: ссылка на [docs/privacy.md](privacy.md) в этом репозитории.
   - Возрастной рейтинг: анкета IARC, у Orbit нет пользовательского контента и покупок.
   - Ограниченная возможность `runFullTrust`. Объяснение: «Orbit is a desktop remote-control app. It captures the screen and injects mouse and keyboard input with Win32 APIs (SendInput), which requires a full-trust desktop process.»
   - Скриншоты: подойдут файлы из `docs/screenshots`.

Проверка обычно занимает от нескольких часов до трёх дней. После публикации добавьте ссылку на Store в README.

Пакет из Store отличается от `.exe` в двух местах. Автозапуск включается в «Параметры → Приложения → Автозагрузка» (Orbit показывает кнопку Open Startup apps вместо переключателя). Правило брандмауэра для портов 47800/TCP и 47801/UDP ставится вместе с пакетом, поэтому строки Windows Firewall в настройках нет.

## SignPath Foundation

[SignPath Foundation](https://signpath.org) бесплатно подписывает open source проекты своим сертификатом. В свойствах файла издателем будет указан SignPath Foundation. SmartScreen всё ещё может предупреждать первые недели, пока у сертификата копится репутация для этого файла.

1. Подайте заявку на [signpath.org/apply](https://signpath.org/apply). Нужны открытый репозиторий, лицензия OSI (у Orbit MIT) и сборка в CI, что уже есть.
2. После одобрения в SignPath создайте проект `orbit-remote`, подключите его к GitHub как Trusted Build System и создайте политику подписи `release-signing`.
3. Конфигурация артефакта: zip, внутри которого `Orbit.exe` подписывается как `pe-file`:

   ```xml
   <artifact-configuration xmlns="http://signpath.io/artifact-configuration/v1">
     <zip-file>
       <pe-file path="Orbit.exe">
         <authenticode-sign />
       </pe-file>
     </zip-file>
   </artifact-configuration>
   ```

4. Добавьте токен и идентификатор организации:

   ```bash
   gh secret set SIGNPATH_API_TOKEN
   gh variable set SIGNPATH_ORGANIZATION_ID --body "<id из SignPath>"
   ```

   Если проект или политика называются иначе, задайте `SIGNPATH_PROJECT_SLUG` и `SIGNPATH_POLICY_SLUG`.

Как только секрет появится, workflow начнёт отправлять `Orbit.exe` на подпись и класть в релиз уже подписанный файл. Без секрета эти шаги пропускаются.

## Свой сертификат

Если вы купили сертификат подписи кода (OV или EV), его можно подключить через секреты `WINDOWS_CERT_PFX_BASE64` (файл `.pfx` в base64) и `WINDOWS_CERT_PASSWORD`:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("cert.pfx")) | gh secret set WINDOWS_CERT_PFX_BASE64
gh secret set WINDOWS_CERT_PASSWORD
```

С июня 2023 года удостоверяющие центры выдают ключи только на токене или в облачном HSM, и выгрузить их в `.pfx` обычно нельзя. В этом случае вместо шага с `.pfx` нужен инструмент вашего центра (например, DigiCert KeyLocker или SSL.com eSigner) или Azure Artifact Signing. Последний пока доступен частным лицам только в США и Канаде.

## Android

APK подписан постоянным ключом проекта. Отпечаток SHA-256 сертификата:

```
12:1A:C6:CA:E8:35:6F:4B:FE:D6:E5:69:02:3B:8D:D2:11:1D:4E:71:FA:F2:6B:D0:23:01:18:23:ED:3D:5F:40
```

Ключ хранится в секретах репозитория (`ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`). Держите копию keystore вне GitHub: если его потерять, обновления перестанут ставиться поверх старой версии.

### Проверка разработчика

Google постепенно вводит обязательную проверку разработчиков. Сейчас она действует только в отдельных странах. Установку APK вне Play в остальных регионах она пока не затрагивает, а глобальное включение запланировано на 2027 год. Чтобы Orbit продолжал ставиться и после этого:

1. Зарегистрируйтесь в [Android Developer Console](https://developer.android.com/developer-verification) и пройдите проверку личности.
2. Добавьте пакет `dev.orbitremote.app` и подтвердите владение, указав отпечаток ключа выше.

Для тестирования есть бесплатный аккаунт с ограниченным распространением: без проверки документов, но установка только на 20 устройств.

### Google Play

1. Создайте аккаунт в [Play Console](https://play.google.com/console), регистрационный взнос 25 долларов.
2. Создайте приложение и включите Play App Signing. Загрузите ключ проекта, чтобы версии из Play и с GitHub обновляли друг друга.
3. Скачайте артефакт `store-android-aab` (`Orbit-Android-Play.aab`) из запуска workflow для тега.
4. Новые личные аккаунты сначала должны провести закрытое тестирование: не меньше 12 тестировщиков в течение 14 дней. После этого можно запросить доступ к рабочей версии.
5. В анкете о данных укажите, что приложение не собирает данные, и дайте ссылку на [docs/privacy.md](privacy.md).
