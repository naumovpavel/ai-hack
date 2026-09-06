from __future__ import annotations

import re

# Only these broad labels leave the real interview's private question set. Exact
# topics/competencies often contain the answer, a project detail, or screening hints.
TOPIC_CATEGORIES = (
    ("Python", ("python", "питон", "asyncio", "gil", "fastapi", "django")),
    ("Базы данных", (
        "sql", "postgresql", "postgres", "mysql", "sqlite", "sqlalchemy", "mongodb",
        "database", "databases", "баз", "clickhouse", "etl", "индекс", "данных",
    )),
    ("Интеграции", (
        "kafka", "rabbit", "rabbitmq", "очеред", "брокер", "api", "apis", "интеграц", "событи",
    )),
    ("Инфраструктура", ("docker", "kubernetes", "devops", "sre", "инцидент", "монитор")),
    ("Архитектура", (
        "architecture", "system design", "software design", "design patterns",
        "архитект", "микросервис", "масштаб", "систем", "проектирован",
    )),
    ("Тестирование", ("тест", "test", "testing", "pytest", "qa", "качество", "отлад")),
    ("Безопасность", ("безопас", "security", "аутентиф", "авторизац")),
    ("Веб-разработка", ("javascript", "typescript", "react", "frontend", "css", "html")),
    ("Мобильная разработка", ("android", "ios", "flutter", "мобиль")),
    ("Аналитика", ("аналити", "статист", "машинн", "machine learning", "модел")),
    ("Программирование", ("алгоритм", "структур", "java", "golang", "ооп", "программ")),
    ("Управление продуктом", ("продукт", "product", "приоритет", "метрик", "планирован")),
    ("Дизайн", ("дизайн", "design", "ux", "ui", "интерфейс")),
    ("Продажи и маркетинг", ("продаж", "маркет", "sales", "клиент")),
    ("Финансы", ("финанс", "бюджет", "учет", "эконом")),
    ("Опыт и работа в команде", (
        "опыт", "команд", "мотивац", "ожидан", "ответствен", "коммуникац", "review", "ревью",
    )),
)


def _topic_pattern(key: str) -> re.Pattern[str]:
    # Latin technology names are whole tokens/phrases. Russian entries deliberately
    # use stems at the beginning of a word to cover ordinary inflections.
    suffix = r"[а-яё]*\b" if re.search("[а-яё]", key) else r"\b"
    escaped = re.escape(key).replace(r"\ ", r"\s+")
    return re.compile(r"\b" + escaped + suffix)


TOPIC_PATTERNS = tuple(
    (name, tuple(_topic_pattern(key) for key in keys)) for name, keys in TOPIC_CATEGORIES
)
EXPLICIT_INTERFACE_PATTERNS = tuple(
    _topic_pattern(key) for key in ("ux", "ui", "интерфейс", "дизайн")
)
TECHNICAL_DESIGN_DOMAINS = {"Архитектура", "Базы данных", "Интеграции", "Программирование"}


def broad_topics(values: list[str]) -> list[str]:
    labels: list[str] = []
    for value in values:
        lowered = value.casefold()
        matches = [
            name for name, patterns in TOPIC_PATTERNS
            if any(pattern.search(lowered) for pattern in patterns)
        ]
        # Architecture & Design and database/API design describe technical design,
        # not an additional visual/UX interview topic. Explicit UX labels still count.
        if ("Дизайн" in matches and TECHNICAL_DESIGN_DOMAINS.intersection(matches)
            and not any(pattern.search(lowered) for pattern in EXPLICIT_INTERFACE_PATTERNS)):
            matches.remove("Дизайн")
        for label in matches or ["Профессиональная практика"]:
            if label not in labels:
                labels.append(label)
    return labels or ["Профессиональная практика"]


PRACTICE_EXAMPLES = {
    "Python": [
        "В учебной программе несколько задач меняют один список. Как понять, "
        "кто владеет данными, и избежать неожиданных изменений?",
        "Нужно обработать большой текстовый файл на Python при ограниченной памяти. "
        "Как организовать чтение и обработку и проверить расход памяти?",
        "Python-программа обращается к нескольким медленным внешним сервисам. "
        "Как ограничить время ожидания и корректно завершить оставшиеся операции?",
    ],
    "Базы данных": [
        "В учебной системе история событий быстро растёт, но старые данные редко нужны. "
        "Как организовать хранение и удаление истории, сохраняя полезные отчёты?",
        "После переноса данных в новую таблицу часть записей пропала. "
        "Как вы сверите результат миграции и подготовите безопасное повторение?",
        "Два пользователя одновременно редактируют одну запись. "
        "Какие варианты разрешения конфликта вы предложите и как объясните их пользователю?",
    ],
    "Интеграции": [
        "Внешний API стал отвечать медленно и иногда возвращает ошибку. "
        "Как ограничить влияние этой зависимости на ваш сервис?",
        "Партнёр меняет формат поля в ответе своего API. "
        "Как подготовить совместимое изменение и проверить, что старые клиенты не сломались?",
        "При интеграции двух учебных сервисов их часы расходятся. "
        "Какие проблемы это создаст и как вы будете связывать события при отладке?",
    ],
    "Инфраструктура": [
        "После выпуска новой версии выросло потребление памяти. "
        "Как вы отделите утечку от обычного изменения нагрузки и проверите гипотезу?",
        "Учебному сервису нужно менять конфигурацию без пересборки образа. "
        "Как организовать конфигурацию, проверку и откат?",
        "У фонового задания внезапно заканчивается место на диске. "
        "Как найти причину и предупредить повторение ситуации?",
    ],
    "Опыт и работа в команде": [
        "Коллега предлагает быстрее выпустить задачу, сократив проверку. "
        "Как вы обсудите риски и договоритесь о приемлемом объёме работы?",
        "Вы понимаете, что не успеваете выполнить обещанный объём задачи. "
        "Как сообщите об этом команде и предложите дальнейшие действия?",
        "Новому участнику команды непонятно ваше решение. "
        "Как вы объясните его и проверите, что обсуждение помогло?",
    ],
}


def fallback_questions(topic: str) -> list[str]:
    return PRACTICE_EXAMPLES.get(topic, []) + [
        f"Возьмём тему «{topic}». В учебном проекте результат работает на простом примере, "
        "но ломается при изменении условий. Как вы построите проверку гипотез и найдёте причину?",
        f"Представьте, что обучаете нового коллегу теме «{topic}». "
        "Какой небольшой практический пример вы выберете и какую типичную ошибку разберёте?",
        f"В области «{topic}» вам предложили непривычный подход. "
        "Какие ограничения вы выясните и как проверите его пригодность на небольшом эксперименте?",
    ]
