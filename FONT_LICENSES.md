# Шрифты для чтения

В приложение включены неизменённые открытые шрифты, работающие без загрузки из сети. Файлы находятся в `src/malferma_libro/assets/fonts/` и регистрируются в Fontconfig только для текущего процесса; системные настройки шрифтов не изменяются.

| Семейство | Файл в assets/fonts | Версия | Для чего |
| --- | --- | --- | --- |
| Noto Serif | `NotoSerif-Regular.ttf` | 2.004 | Основной книжный шрифт с засечками |
| Noto Sans | `NotoSans-Regular.ttf` | 2.004 | Шрифт без засечек с ясными очертаниями |
| Liberation Serif | `LiberationSerif-Regular.ttf` | 2.1.5 | Более компактный традиционный шрифт с засечками |
| Noto Naskh Arabic | `NotoNaskhArabic-Regular.ttf` | 2.004 | Арабское письмо и фарси, книжный стиль |
| Noto Sans Arabic | `NotoSansArabic-Regular.ttf` | 2.005 | Арабское письмо и фарси без засечек |
| Noto Serif Hebrew | `NotoSerifHebrew-Regular.ttf` | 2.000 | Иврит и идиш, книжный стиль |
| Noto Sans Hebrew | `NotoSansHebrew-Regular.ttf` | 3.000 | Иврит и идиш без засечек |
| Noto Serif Ethiopic | `NotoSerifEthiopic-Regular.ttf` | 2.000 | Эфиопское письмо, амхарский книжный текст |
| Noto Sans Ethiopic | `NotoSansEthiopic-Regular.ttf` | 2.000 | Эфиопское письмо без засечек |

Также доступен системный шрифт Debian. В выборе остаются Noto Serif,
Noto Sans и Liberation Serif: соответствующие шрифты Arabic/Hebrew/Ethiopic
подключаются автоматически для своих письменностей. Выбор относится
к тексту книги; интерфейс использует системную гарнитуру с Fontconfig fallback.

Основные семейства предназначены для латиницы и кириллицы, а дополнительные
Arabic/Hebrew/Ethiopic — для соответствующих письменностей. Отображение
использует Pango и Fontconfig fallback. Наличие шрифта не означает покрытия
всех символов Unicode; языковой и экранный контроль следует проводить в
живом графическом сеансе. SHA-256 включённых TTF сохранены ниже.

Все включённые семейства Noto: Copyright 2010, 2012–2020 Google Inc.;
2015–2020 Google LLC. Точные уведомления сохранены в LICENSE-Noto.txt. Лицензия SIL Open Font License 1.1. Источник: Debian `fonts-noto-core`, upstream <https://github.com/notofonts/noto-fonts>. Уведомления и полный текст лицензии включены в `src/malferma_libro/assets/fonts/LICENSE-Noto.txt` (сохранён файл copyright пакета Debian).

Liberation Serif: Digitized data copyright (c) 2010 Google Corporation; Copyright (c) 2012 Red Hat, Inc. Лицензия SIL Open Font License 1.1. Источник: Debian `fonts-liberation`, upstream <https://github.com/liberationfonts/liberation-fonts>. Уведомления, зарезервированные имена и полный текст лицензии включены в `src/malferma_libro/assets/fonts/LICENSE-Liberation.txt` (сохранён файл copyright пакета Debian).

Лицензия приложения GPL-3.0-or-later не меняет лицензию шрифтов.

SHA-256 неизменённых файлов:

```
9d7583b7dc9e812afd32a14280c5cac3160012efe50c8d08938f4fea266ff67f  NotoSerif-Regular.ttf
89c3c497f618fdaa0b2d1e98fef93582f28c71debd2c4a8cdf41f190ced2909d  NotoSans-Regular.ttf
9caef765d2e891c10dd73658894f01e660fe0c1c83e0bda7d6edf561d8f623d4  LiberationSerif-Regular.ttf
8c67eaa2f0086872628fc3f7f760386f83c8be5c5e9a1ba3a38891237b2ac7cb  NotoNaskhArabic-Regular.ttf
504d7407d86875acf7d04dfaa0fd7524d0b8797723bc4aa18022f29db25b0b6e  NotoSansArabic-Regular.ttf
436900d5ad77d33e4234247f3076eaecd25b92b9bea0519514f684140e3566a7  NotoSansHebrew-Regular.ttf
789b7e7e3ff4d95a5e105872a385db12c50c08b60ad5b773d25a3bec86621abf  NotoSerifHebrew-Regular.ttf
58bc43b062961b38ee45757d2e74e6a991a12011aa0399fb03004ac432e5c852  NotoSansEthiopic-Regular.ttf
30bd9e21c81cd95a3004bbf75aba9b2ab5f861408a3fbb4f82b10fe82072952b  NotoSerifEthiopic-Regular.ttf
```
