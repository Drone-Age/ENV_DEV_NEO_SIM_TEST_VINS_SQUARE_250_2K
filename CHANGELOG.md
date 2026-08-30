# Історія змін

## 1.0.7 — геометрична перевірка найкращого DBoW-кандидата

- Активні режими поточної сесії використовують `candidate_selection=best_score`.
- Upstream-сумісна політика `oldest` залишається типовою для решти режимів.
- Fundamental/PnP, cheirality, quadrant і consistency gates не послаблено.

Issue: https://github.com/Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K/issues/1

## 1.0.6 — виключення одного повного кола

- Збільшено `candidate_exclusion_keyframes` до 400 для активних режимів із
  keyframe поточного запуску. Значення випливає з фактично виміряного рознесення
  відповідних кадрів двох кіл приблизно на 412 keyframe.
- Мета зміни — не допустити витіснення правильного кандидата першого кола
  візуально схожими, але просторово неправильними недавніми кадрами.
- Перекомпіляція VINS не потрібна: використовується параметр загального механізму
  VINS-NEO, доданий у межах компонентного Issue.

Issue: https://github.com/Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K/issues/1

## 1.0.5 — ранній Loop Closure і повне corrected evidence

- Додано підписаний параметр `candidate_exclusion_keyframes`: 250 keyframes
  для режимів із loop поточної сесії та 50 для решти режимів.
- Усунуто домінування недавніх DBoW-кандидатів на довгих повторних сторонах
  квадрата без послаблення геометричної перевірки match.
- Метрики відновлюють corrected-пари, які надійшли із запізненням, лише за
  тотожним source timestamp; окремий evidence-файл фіксує кожне відновлення.
- Зміни виконано за
  `https://github.com/Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K/issues/1`.

## 1.0.4 — повний pre-ARM startup retry contract

- Явний `SIM Gateway published no status sample` класифікується як доведена
  startup failure і допускає один чистий retry до ARM.
- Класифікатор охоплює Gazebo, SITL, camera, ROS bridge, SIM Gateway,
  iMAVROS і VINS, але лише з точними timeout/not-ready формулюваннями.
- Будь-яка ознака `GATEWAY_LOITER_BOOTSTRAP_STARTED` або `armed=true` і надалі
  забороняє retry.
- Evidence v1.0.3 зберігається; офіційна кампанія запускається з profile
  SHA-256 v1.0.4.

Issue: https://github.com/Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K/issues/1
Координація: https://github.com/Drone-Age/ENV_DEV_NEO_SIM1/issues/12

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
