# Історія змін

## 1.0.3 — ізоляція smoke-критеріїв

- `engineering_smoke_expectations` більше не успадковується 42 офіційними
  профілями кампанії.
- Identity gate для `disabled` не може помилково класифікувати коректний
  `loop`, `map_reuse_only` або комбінований corrected stream як FAIL.
- Польоти версії 1.0.2 зберігаються як engineering evidence; офіційна
  кампанія починається заново з точними profile SHA-256 версії 1.0.3.

Issue: https://github.com/Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K/issues/1
Координація: https://github.com/Drone-Age/ENV_DEV_NEO_SIM1/issues/12

## 1.0.2 — канонічне володіння evidence

- Route qualification автоматично зберігає evidence у `logs/` того тестового
  репозиторію, якому належить активний profile.
- Launcher читає фактичний канонічний каталог через `latest_run_dir` і більше
  не створює порожню копію у сторонньому `flight-evidence`.
- Resume і консолідація кампанії тепер бачать завершені польоти без ручного
  перенесення даних.

Issue: https://github.com/Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K/issues/1
Координація: https://github.com/Drone-Age/ENV_DEV_NEO_SIM1/issues/12

## 1.0.1 — гарантія фактичної дистанції

- Після двох повних кіл додано замкнений 20+20 м distance-assurance tail.
- Tail зберігає endpoint у першій вершині й не входить у lap/side/corner
  метрики.
- Це гарантує gate `SIM truth distance >= 2000 м` попри штатне заокруглення
  кутів ArduCopter.

Issue: https://github.com/Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K/issues/1

## 1.0.0 — початкова кваліфікація квадрата 2 км

- Додано квадрат 250×250 м на висотах 150 і 40 м, два круги та рівно 2000 м
  канонічної route distance.
- Підліт до першої вершини виключено з route metrics через зафіксований
  `route_start_sequence`.
- Додано п'ять smoke запусків і незмінну кампанію з 42 польотів.
- Додано режими `disabled`, `loop`, `map_build`, `map_reuse_only` та
  `loop_and_map_reuse` із match windows першого й другого кругів.
- Додано незалежні контракти `simulation` і `real_vehicle`; реальний backend
  працює fail-closed і не запускає Gazebo.
- RTK/PPK і SIM truth заборонено використовувати як вхід VINS/Pose Graph.
- ArduCopter зафіксовано на 4.7.0, commit
  `1511f27194f1dcc3728270883047bdf022b3fd53`.
- Rosbag/MCAP вимкнено без прямої директиви користувача для конкретного run.

Issue: https://github.com/Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K/issues/1
Координація: https://github.com/Drone-Age/ENV_DEV_NEO_SIM1/issues/12
