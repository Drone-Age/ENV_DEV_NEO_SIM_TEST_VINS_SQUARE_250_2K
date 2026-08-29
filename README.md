# Кваліфікація VINS Pose Graph на квадраті 250 м / 2 км

Окремий test case для VINS-NEO Loop Closure і Map Reuse. Маршрут — квадрат
250×250 м, два повні круги та не менше 2000 м залікової дистанції. Підліт до
першої вершини і повернення не входять до route metrics.

Issue: https://github.com/Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K/issues/1

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

## Rosbag

Rosbag/MCAP завжди вимкнено. `suite`, `backend`, `headless` або profile не
можуть увімкнути recorder. Лише пряма опція `-Rosbag`, явно дозволена
користувачем для конкретного запуску, передається runtime.
