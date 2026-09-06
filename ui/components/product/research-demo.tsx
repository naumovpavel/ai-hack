import type { ReactNode } from 'react';
import {
  BookOpen,
  GraduationCap,
  MessageSquare,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';

export const researchDemoSteps: {
  title: string;
  intro: string;
  icon: typeof BookOpen;
  content: ReactNode;
}[] = [
  {
    title: 'До старта вы знаете, что вас ждёт',
    icon: BookOpen,
    intro:
      'Заранее показываем темы интервью, длительность и правила прохождения. Объясняем, что делает ИИ, что будет записываться и кто принимает решение.',
    content: (
      <div className="space-y-6">
        <div>
          <p className="text-sm font-medium text-accent-foreground">
            Пример тем, которые вы увидите до начала
          </p>
          <ul className="mt-3 flex flex-wrap gap-2">
            {[
              'Работа с рисками',
              'Приоритизация задач',
              'Взаимодействие с командой',
            ].map((topic) => (
              <li
                key={topic}
                className="rounded-full bg-muted px-4 py-2 text-sm"
              >
                {topic}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
            По этим темам можно подготовиться. Конкретные вопросы зависят от
            вакансии и хода интервью.
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-xl border p-5">
            <h3 className="font-semibold">Роль ИИ</h3>
            <p className="mt-2 leading-relaxed">
              Задать вопросы, при необходимости уточнить ответ и подготовить
              разбор с аргументами.
            </p>
          </div>
          <div className="rounded-xl border p-5">
            <h3 className="font-semibold">Роль человека</h3>
            <p className="mt-2 leading-relaxed">
              Проверить ответы и выводы ИИ, принять решение и написать вам
              обратную связь.
            </p>
          </div>
        </div>
        <div className="rounded-xl bg-muted/70 p-5">
          <h3 className="font-semibold">Понятный порядок прохождения</h3>
          <p className="mt-2 leading-relaxed">
            Подготовка и пробное интервью → основное интервью → проверка
            командой → решение с фидбэком. До начала вы видите лимит времени,
            условия записи и проверяете технику.
          </p>
        </div>
        <p className="text-sm leading-relaxed text-muted-foreground">
          Основное интервью записывается с камеры и микрофона. Если включён
          контроль прохождения, записывается и выбранный вами экран. Условия и
          согласие показываются до старта.
        </p>
      </div>
    ),
  },
  {
    title: 'Сначала можно попробовать на тренировке',
    icon: GraduationCap,
    intro:
      'Пройдите пробное, или мок-интервью, по тем же общим темам. В нём используются отдельные тренировочные вопросы. Так можно освоиться с форматом до настоящего интервью.',
    content: (
      <div className="space-y-5">
        <div>
          <p className="text-sm font-medium text-accent-foreground">
            Пример тренировочного вопроса · работа с рисками
          </p>
          <p className="mt-2 text-lg leading-relaxed">
            «Расскажите о ситуации, когда задача могла не уложиться в срок. Как
            вы действовали?»
          </p>
        </div>
        <div className="rounded-xl bg-muted/70 p-5">
          <h3 className="font-semibold">
            Вы увидите анализ в том же формате, что и HR
          </h3>
          <p className="mt-2 leading-relaxed">
            В разборе — ваши ответы, оценка по критериям, аргументы, цитаты и
            пункты, которые стоит раскрыть подробнее. Именно таким форматом
            пользуется HR при проверке основного интервью.
          </p>
        </div>
        <div className="rounded-xl border p-5">
          <p className="text-sm font-medium text-accent-foreground">
            Пример фрагмента разбора тренировки
          </p>
          <p className="mt-3 font-medium">Работа с рисками</p>
          <p className="mt-2 leading-relaxed">
            Вы предупредили команду о задержке и предложили изменить объём
            задачи. Пока неясно, как вы выбирали, что можно перенести.
          </p>
          <p className="mt-3 text-sm text-muted-foreground">
            Идея для подготовки: вспомнить критерии выбора приоритетов и
            результат своего решения.
          </p>
        </div>
        <p className="leading-relaxed">
          Сначала оцените собственные ответы, затем откройте общие выводы ИИ,
          сравните оценки и составьте план подготовки.
        </p>
        <div className="flex items-start gap-3 rounded-xl bg-muted/70 p-4">
          <ShieldCheck className="mt-1 size-5 shrink-0 text-accent-foreground" />
          <p className="text-sm leading-relaxed">
            Ответы и анализ тренировки доступны только вам. HR их не увидит, и
            настоящее интервью не начнётся автоматически.
          </p>
        </div>
      </div>
    ),
  },
  {
    title: 'Показываем, на чём основан анализ',
    icon: Sparkles,
    intro:
      'ИИ переводит запись в текст и сопоставляет содержание ответов с критериями вакансии. В отчёте есть аргументы, цитаты и связанные фрагменты записи, по которым можно проверить выводы.',
    content: (
      <div className="space-y-5">
        <div>
          <p className="text-sm font-medium text-accent-foreground">
            Пример ответа кандидата
          </p>
          <blockquote className="mt-3 border-l-2 border-primary pl-4 text-lg leading-relaxed">
            «За два дня до релиза я понял, что не успеваю. Предупредил команду,
            предложил выпустить основную часть, а остальное перенести. Мы
            согласовали новый план».
          </blockquote>
        </div>
        <div className="rounded-xl border p-5">
          <p className="text-sm text-muted-foreground">Критерий</p>
          <h3 className="mt-1 font-semibold">Работа с рисками</h3>
          <p className="mt-4 text-sm font-medium text-accent-foreground">
            Основание вывода
          </p>
          <p className="mt-2 leading-relaxed">
            Кандидат сообщил о риске до релиза и предложил способ сократить
            объём работы.
          </p>
          <blockquote className="mt-3 rounded-lg bg-muted/70 p-4 leading-relaxed">
            «Предупредил команду, предложил выпустить основную часть».
          </blockquote>
        </div>
        <div className="rounded-xl bg-muted/70 p-5">
          <h3 className="font-semibold">Что пока не раскрыто</h3>
          <p className="mt-2 leading-relaxed">
            В ответе не объяснено, как были определены приоритеты. Это повод
            уточнить, какие задачи можно было перенести и почему.
          </p>
        </div>
        <p className="text-sm leading-relaxed text-muted-foreground">
          В разборе отдельно отмечаются подтверждённые пункты и то, для чего не
          хватает данных. HR может проверить аргументы по исходным ответам.
        </p>
      </div>
    ),
  },
  {
    title: 'HR сначала формирует собственное решение',
    icon: ShieldCheck,
    intro:
      'Процесс устроен так, чтобы рекрутер самостоятельно рассмотрел кандидата. Общий вывод и рекомендация ИИ открываются только после сохранения первичного решения человека.',
    content: (
      <div className="space-y-5">
        <ol className="space-y-4">
          <li className="flex gap-4">
            <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted font-medium">
              1
            </span>
            <div>
              <h3 className="font-semibold">Оценить каждый ответ</h3>
              <p className="mt-1 leading-relaxed">
                HR изучает ответы и доступные аргументы по ним, отмечает, где
                данных достаточно, недостаточно или нужна проверка.
              </p>
            </div>
          </li>
          <li className="flex gap-4">
            <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted font-medium">
              2
            </span>
            <div>
              <h3 className="font-semibold">Записать своё решение и фидбэк</h3>
              <p className="mt-1 leading-relaxed">
                Пока этого нет, итоговая рекомендация ИИ скрыта. Оценки
                отдельных ответов сами по себе её не открывают.
              </p>
            </div>
          </li>
          <li className="flex gap-4">
            <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted font-medium">
              3
            </span>
            <div>
              <h3 className="font-semibold">
                Сравнить выводы и подтвердить решение
              </h3>
              <p className="mt-1 leading-relaxed">
                HR может сохранить свою позицию. Если рекомендация ИИ меняет
                решение, нужно объяснить причину изменения.
              </p>
            </div>
          </li>
        </ol>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-xl border p-5">
            <p className="text-sm text-muted-foreground">
              Первичное решение HR
            </p>
            <p className="mt-2 font-medium">Пригласить на следующий этап</p>
            <p className="mt-2 text-sm leading-relaxed">
              Есть конкретный пример работы с риском.
            </p>
          </div>
          <div className="rounded-xl border p-5">
            <p className="text-sm text-muted-foreground">
              Открытая затем рекомендация ИИ
            </p>
            <p className="mt-2 font-medium">Нужна дополнительная проверка</p>
            <p className="mt-2 text-sm leading-relaxed">
              Недостаточно сведений о выборе приоритетов.
            </p>
          </div>
        </div>
        <div className="rounded-xl bg-muted/70 p-5">
          <h3 className="font-semibold">
            В этом примере HR сохраняет своё решение
          </h3>
          <p className="mt-2 leading-relaxed">
            Он приглашает кандидата и планирует подробнее обсудить приоритеты на
            следующем этапе. Финальное решение подтверждает человек.
          </p>
        </div>
      </div>
    ),
  },
  {
    title: 'При любом решении вы получите фидбэк',
    icon: MessageSquare,
    intro:
      'Обратная связь обязательна и при приглашении, и при отказе. Сервис не позволит HR подтвердить окончательное решение без комментария кандидату.',
    content: (
      <div className="space-y-5">
        <div className="rounded-xl border p-5">
          <p className="text-sm font-medium text-accent-foreground">
            Пример сообщения кандидату после решения
          </p>
          <h3 className="mt-3 text-xl font-semibold">
            Приглашаем на следующий этап
          </h3>
          <p className="mt-3 leading-relaxed">
            «Вы привели конкретный пример: заранее сообщили команде о риске и
            предложили изменить объём релиза. На следующей встрече хотим
            подробнее обсудить, как вы определяете приоритеты при ограниченных
            сроках».
          </p>
        </div>
        <div className="rounded-xl bg-muted/70 p-5">
          <h3 className="font-semibold">Результат и объяснение — вместе</h3>
          <p className="mt-2 leading-relaxed">
            После подтверждения решения HR вы увидите статус и его комментарий
            на своей странице интервью. Это правило действует и для отказа:
            оставить итог без обратной связи нельзя.
          </p>
        </div>
        <p className="leading-relaxed">
          Так у вас остаётся понятный результат рассмотрения и обратная связь от
          команды, с которой вы проходили отбор.
        </p>
      </div>
    ),
  },
];
