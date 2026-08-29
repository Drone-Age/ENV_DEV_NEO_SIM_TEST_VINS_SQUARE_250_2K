# Версіонування

Репозиторій використовує Semantic Versioning та immutable annotated tags
`vMAJOR.MINOR.PATCH`.

- `MAJOR` — несумісна зміна маршруту, backend contract, evidence або verdict;
- `MINOR` — сумісне додавання метрики, режиму чи report;
- `PATCH` — сумісне виправлення test oracle або генератора.

Profiles, test contract, `VERSION`, CHANGELOG і release evidence змінюються
разом. SIM1 використовує лише точний released commit через submodule.

Issue: https://github.com/Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K/issues/1
