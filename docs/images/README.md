# Изображения схем

Здесь лежат картинки FBD-схем для README. Они **отрисованы из сгенерированных
PLCopenXML** (те же файлы, что создаёт `generator/gen_stage4.py` в
`src/s4_pous/*.plcopenxml`), а не нарисованы вручную и не вырезаны из
редактора CODESYS.

## Чем созданы

`tools/render_fbd.py` — Python 3 без сторонних библиотек: читает PLCopenXML,
берёт координаты блоков (`<position x y>`) и связи (`<connection refLocalId>`)
и пишет SVG.

```powershell
cd tools
# одна сеть
python render_fbd.py ..\src\s4_pous\FB_IO_Dispatch.plcopenxml 0 out.svg --title "FB_IO_Dispatch, сеть 1"
# все сети POU подряд
python render_fbd.py ..\src\s4_pous\FB_Watchdog.plcopenxml all out.svg --title "FB_Watchdog"
```

PNG-копии (для README) получены из SVG headless-браузером:

```powershell
msedge --headless --disable-gpu --hide-scrollbars --screenshot=out.png --window-size=650,796 file:///C:/.../out.svg
```

## Состав

| Файл | Что на картинке |
|---|---|
| `img_fb_io_dispatch_port.*` | `FB_IO_Dispatch`, сеть 1: дескриптор порта `GVL_IO_Map.Map[Port]` |
| `img_fb_io_fault.*` | `FB_IO_Dispatch`, сеть 5: политика порта без канала — `STUB` / `DIAG_OK` / `FAULT` |
| `img_fb_watchdog_event.*` | `FB_Watchdog`, сеть 5: событие тайм-аута такта |
| `img_plc_prg_reset.*` | `PLC_PRG_CPM`, сеть 3: сброс CP/M (выключить процессор → PC/SP → включить) |

## Почему не скриншот из CODESYS

В CODESYS 3.5 SP17 картинку POU отдаёт только внутренний компонент редактора
(`Common/POUImage.dll`, интерфейс `_3S.CoDeSys.POUImage.IPOUImageProperty`;
он **не** входит в скриптовый API), поэтому снимок возможен только вручную из
GUI. Рендер из PLCopenXML показывает ровно то, что лежит в репозитории, и
воспроизводится одной командой.
