# Кваліфікація VINS Pose Graph на квадраті 250 м / 2 км

Окремий test case для VINS-NEO Loop Closure і Map Reuse. Маршрут — квадрат
250×250 м, два повні круги та не менше 2000 м залікової дистанції. Підліт до
першої вершини і повернення не входять до route metrics.

Після двох кіл місія виконує замкнений 20+20 м distance-assurance tail уздовж
першої сторони. Він компенсує штатне заокруглення кутів ArduCopter, зберігає
endpoint у першій вершині та не входить у lap/side/corner метрики.

Issue: https://github.com/Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K/issues/1

GPS-denied підкампанія: https://github.com/Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K/issues/2

## Межа відповідальності

- спільне ядро володіє маршрутами, profiles, suites, verdicts і JSON/PDF;
- `simulation` adapter запускається через ENV_DEV_NEO_SIM1;
- `real_vehicle` не запускає Gazebo та вимагає затверджений site profile,
  геозону, RTL, часову синхронізацію й RTK/PPK metadata;
- reference data ніколи не надходить до VINS або Pose Graph;
- ArduCopter зафіксовано на 4.7.0, commit
  `1511f27194f1dcc3728270883047bdf022b3fd53`.

## Перевірка без польоту

```powershell
python .\generate_mission.py
python .\generate_pose_graph_campaign.py
.\run-test.ps1 -Suite vins-mono-square-250-2k-pose-graph-42 -Backend simulation -PrintOnly -Headless
python -m pytest -q .\test_contract.py
```

Fail-closed dry run майбутнього реального backend потребує заповнені й
затверджені `-SiteProfile` та, для PPK, `-ReferenceFile`. Шаблони навмисно не
можуть дозволити ARM.

## Запуск кампанії SIM1

```powershell
.\run-test.ps1 -Suite vins-mono-square-250-2k-pose-graph-smoke -Backend simulation -Headless
.\run-test.ps1 -Suite vins-mono-square-250-2k-pose-graph-42 -Backend simulation -Headless -Resume
```

Офіційна кампанія містить 42 польоти: 10 Loop Closure, 2 Map Build, 18 Map
Reuse Only та 12 Loop Closure + Map Reuse. Smoke містить п'ять окремих
інженерних запусків і не входить до офіційної статистики.

42-польотна кампанія заморожена на профілях версії 1.0.9 і керуванні GNSS
Source Set 1. Її profiles, evidence та звіти не перегенеровуються версією 1.1.0.

## GPS-denied підкампанія

Окрема suite містить 15 польотів на висоті 150 м: по три фіксовані seeds для
`disabled`, `loop`, `map_build`, `map_reuse_only` і
`loop_and_map_reuse`. До офіційної підкампанії виконується один engineering
smoke. Після bootstrap controller переводить ArduCopter на EKF Source Set 2 з
VINS ExternalNav і fail-closed перевіряє health, rate, timestamps, covariance,
FCU acknowledgement та фактичний source timeline. Будь-який Source Set 1 або
GNSS fusion після початку маршруту анулює політ.

```powershell
python .\generate_gps_denied_campaign.py
.\run-test.ps1 -Suite vins-square-250-2k-gps-denied-smoke -NavigationMode gps_denied -Backend simulation -Headless
.\run-test.ps1 -Suite vins-square-250-2k-gps-denied-15 -NavigationMode gps_denied -Backend simulation -Headless -Resume
```

Reuse-профілі читають незмінну карту `square-2km-qualification-map-150m`.
Кожний `map_build` пише окремий artifact за seed, тому immutable map не
перезаписується. GPS-denied JSON/PDF мають окремі імена та не змішуються зі
звітом основних 42 польотів.

## Rosbag

Rosbag/MCAP завжди вимкнено. `suite`, `backend`, `headless` або profile не
можуть увімкнути recorder. Лише пряма опція `-Rosbag`, явно дозволена
користувачем для конкретного запуску, передається runtime.
