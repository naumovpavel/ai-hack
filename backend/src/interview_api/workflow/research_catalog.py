"""Reason branches grounded in product discovery; see docs/research.md."""

REASON_OPTIONS = {
    "trust": {
        "yes": [
            {
                "id": "relevant_questions",
                "label": "Ожидаю вопросов, связанных с будущей работой",
                "hypothesis": "PH3",
            },
            {
                "id": "followup",
                "label": "Считаю, что уточняющие вопросы помогут раскрыть мой опыт",
                "hypothesis": "PH3",
            },
            {"id": "evidence", "label": "Ожидаю понятных оснований оценки", "hypothesis": "PH1"},
            {
                "id": "human_review",
                "label": "Рассчитываю, что результат проверит человек",
                "hypothesis": "PH5",
            },
            {
                "id": "fairness",
                "label": "Считаю условия оценки достаточно справедливыми",
                "hypothesis": "PH3",
            },
        ],
        "no": [
            {
                "id": "misunderstanding",
                "label": "Боюсь, что ИИ неправильно поймёт мой опыт или ответы",
                "hypothesis": "PH3",
            },
            {
                "id": "irrelevant_questions",
                "label": "Сомневаюсь, что вопросы будут связаны с будущей работой",
                "hypothesis": "PH3",
            },
            {
                "id": "no_clarification",
                "label": "Боюсь, что не смогу пояснить нестандартный ответ",
                "hypothesis": "PH3",
            },
            {
                "id": "opaque_evaluation",
                "label": "Мне непонятно, как ИИ сделает выводы",
                "hypothesis": "PH1",
            },
            {
                "id": "automatic_rejection",
                "label": "Боюсь автоматического отказа без проверки человеком",
                "hypothesis": "PH5",
            },
            {
                "id": "unfair_evaluation",
                "label": "Сомневаюсь, что разных кандидатов оценят справедливо",
                "hypothesis": "PH3",
            },
            {
                "id": "insufficient_information",
                "label": "Пока недостаточно информации, чтобы доверять",
                "hypothesis": "PH4",
            },
        ],
    },
    "readiness": {
        "yes": [
            {
                "id": "convenient_time",
                "label": "Хочу пройти этап в удобное время",
                "hypothesis": "PH4",
            },
            {
                "id": "less_waiting",
                "label": "Хочу меньше ждать между этапами найма",
                "hypothesis": "PH4",
            },
            {
                "id": "clear_rules",
                "label": "Готов(а), если заранее понятны длительность и правила",
                "hypothesis": "PH4",
            },
            {
                "id": "human_contact",
                "label": "Готов(а), если после этого будет общение с человеком",
                "hypothesis": "PH4",
            },
            {
                "id": "useful_feedback",
                "label": "Рассчитываю получить полезную обратную связь",
                "hypothesis": "PH11",
            },
            {
                "id": "data_conditions",
                "label": "Готов(а), если понятно, кто увидит запись и ответы",
                "hypothesis": "PH4",
            },
        ],
        "no": [
            {
                "id": "prefer_person",
                "label": "Предпочитаю сразу общаться с человеком",
                "hypothesis": "PH4",
            },
            {
                "id": "no_reciprocity",
                "label": "Не вижу достаточного участия компании в таком формате",
                "hypothesis": "PH4",
            },
            {
                "id": "unclear_rules",
                "label": "Не хочу тратить время без понятной длительности и правил",
                "hypothesis": "PH4",
            },
            {
                "id": "no_feedback",
                "label": "Не вижу пользы для себя без обратной связи",
                "hypothesis": "PH11",
            },
            {
                "id": "recording_concerns",
                "label": "Не хочу передавать запись или ответы без понятных условий",
                "hypothesis": "PH4",
            },
            {"id": "distrust", "label": "Не доверяю оценке ИИ", "hypothesis": "GENERAL"},
        ],
    },
    "experience": {
        "yes": [
            {
                "id": "convenient_time",
                "label": "Удалось пройти в удобное время",
                "hypothesis": "PH4",
            },
            {
                "id": "clear_rules",
                "label": "Длительность и правила были понятны",
                "hypothesis": "PH4",
            },
            {
                "id": "relevant_questions",
                "label": "Вопросы помогли показать мой опыт",
                "hypothesis": "PH3",
            },
            {
                "id": "followup",
                "label": "Уточнения помогли раскрыть мои ответы",
                "hypothesis": "PH3",
            },
            {
                "id": "useful_feedback",
                "label": "После интервью была полезная обратная связь",
                "hypothesis": "PH11",
            },
            {
                "id": "human_contact",
                "label": "Было понятно, что дальше будет человек",
                "hypothesis": "PH4",
            },
        ],
        "no": [
            {
                "id": "too_long",
                "label": "Прохождение заняло слишком много времени",
                "hypothesis": "PH4",
            },
            {
                "id": "unclear_rules",
                "label": "Длительность или правила были непонятны",
                "hypothesis": "PH4",
            },
            {
                "id": "irrelevant_questions",
                "label": "Вопросы плохо соответствовали моему опыту или вакансии",
                "hypothesis": "PH3",
            },
            {
                "id": "no_clarification",
                "label": "Не хватило возможности пояснить ответ",
                "hypothesis": "PH3",
            },
            {
                "id": "no_feedback",
                "label": "Не получил(а) полезной обратной связи",
                "hypothesis": "PH11",
            },
            {
                "id": "no_human_contact",
                "label": "Не хватало контакта с человеком",
                "hypothesis": "PH4",
            },
        ],
    },
    "solution": {
        "yes": [
            {"id": "clear_process", "label": "Мне понятны этапы и правила", "hypothesis": "PH4"},
            {
                "id": "relevant_questions",
                "label": "Вопросы кажутся связанными с реальной работой",
                "hypothesis": "PH3",
            },
            {
                "id": "followup",
                "label": "Уточнения могут помочь раскрыть мой опыт",
                "hypothesis": "PH3",
            },
            {
                "id": "evidence",
                "label": "Примеры показывают, откуда берётся оценка",
                "hypothesis": "PH1",
            },
            {
                "id": "human_decision",
                "label": "Мне понятна роль человека в принятии решения",
                "hypothesis": "PH5",
            },
            {
                "id": "feedback",
                "label": "Обратная связь команды может быть мне полезна",
                "hypothesis": "PH11",
            },
        ],
        "no": [
            {
                "id": "unclear_process",
                "label": "Мне всё ещё непонятны этапы или правила",
                "hypothesis": "PH4",
            },
            {
                "id": "irrelevant_questions",
                "label": "Не вижу связи вопросов с реальной работой",
                "hypothesis": "PH3",
            },
            {
                "id": "unhelpful_followup",
                "label": "Сомневаюсь, что уточнения помогут раскрыть мой опыт",
                "hypothesis": "PH3",
            },
            {
                "id": "opaque_evaluation",
                "label": "Основания оценки всё ещё непонятны",
                "hypothesis": "PH1",
            },
            {
                "id": "unclear_human_role",
                "label": "Роль человека в принятии решения недостаточно ясна",
                "hypothesis": "PH5",
            },
            {
                "id": "unhelpful_feedback",
                "label": "Не вижу пользы в показанной обратной связи",
                "hypothesis": "PH11",
            },
        ],
    },
}
