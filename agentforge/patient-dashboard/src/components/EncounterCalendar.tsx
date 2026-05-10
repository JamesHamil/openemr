import { useMemo, useState } from 'react';
import { EncounterItem, LoadState } from '../fhir/types';

type CalendarView = 'day' | 'week' | 'month' | 'all';

interface CalendarDay {
  key: string;
  date: Date;
  label: string;
  inMonth: boolean;
  isToday: boolean;
  encounters: EncounterItem[];
}

interface EncounterCalendarProps {
  state: LoadState<EncounterItem[]>;
  emptyMessage: string;
  onReviewVisit?: (encounter: EncounterItem) => void;
}

export function EncounterCalendar({ state, emptyMessage, onReviewVisit }: EncounterCalendarProps) {
  if (state.status === 'loading') {
    return <EncounterShell countLabel="" message="Loading" />;
  }
  if (state.status === 'error') {
    return <EncounterShell countLabel="" message={state.message} tone="error" />;
  }
  if (state.data.length === 0) {
    return <EncounterShell countLabel="0" message={emptyMessage} />;
  }
  return <LoadedEncounterCalendar encounters={state.data} onReviewVisit={onReviewVisit} />;
}

function LoadedEncounterCalendar({
  encounters,
  onReviewVisit,
}: {
  encounters: EncounterItem[];
  onReviewVisit?: (encounter: EncounterItem) => void;
}) {
  const datedEncounters = useMemo(() => normalizeDatedEncounters(encounters), [encounters]);
  const encountersByDate = useMemo(() => groupEncountersByDate(datedEncounters), [datedEncounters]);
  const firstVisitKey = encounterDateKey(datedEncounters[0]) || dateKey(new Date());
  const [view, setView] = useState<CalendarView>('month');
  const [selectedDateKey, setSelectedDateKey] = useState(firstVisitKey);

  const selectedDate = dateFromKey(selectedDateKey);
  const currentMonth = selectedDate.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
  const selectedEncounters = encountersByDate.get(selectedDateKey) || [];

  const monthDays = useMemo(
    () => buildCalendarDays(encountersByDate, selectedDate.getFullYear(), selectedDate.getMonth()),
    [encountersByDate, selectedDate]
  );
  const weekDays = useMemo(() => buildWeekDays(encountersByDate, selectedDate), [encountersByDate, selectedDate]);

  if (!datedEncounters.length) {
    return <EncounterShell countLabel="0" message="No dated visits recorded." />;
  }

  return (
    <section className="af-visit-history-card" aria-label="Encounter History">
      <div className="af-visit-history-card__header">
        <div>
          <p className="af-dashboard-eyebrow">Encounter Calendar</p>
          <h2>Visit History</h2>
        </div>
        <div className="af-visit-history-card__tools">
          <div className="af-visit-view-switch" aria-label="Calendar view">
            {(['day', 'week', 'month', 'all'] as CalendarView[]).map((calendarView) => (
              <button
                aria-pressed={view === calendarView}
                key={calendarView}
                onClick={() => setView(calendarView)}
                type="button"
              >
                {titleCase(calendarView)}
              </button>
            ))}
          </div>
          {view === 'all' ? null : (
            <div className="af-visit-history-card__controls" aria-label="Calendar date range">
              <button type="button" onClick={() => setSelectedDateKey(shiftDate(selectedDate, view, -1))}>
                Previous
              </button>
              <span>{rangeLabel(selectedDate, view)}</span>
              <button type="button" onClick={() => setSelectedDateKey(shiftDate(selectedDate, view, 1))}>
                Next
              </button>
            </div>
          )}
        </div>
      </div>
      <div className="af-visit-history-card__body">
        {view === 'all' ? (
          <AllVisitsView
            encounters={datedEncounters}
            onReviewVisit={onReviewVisit}
            onSelectEncounter={(encounter) => {
              setSelectedDateKey(encounterDateKey(encounter));
              setView('month');
            }}
          />
        ) : null}
        {view === 'month' ? (
          <MonthView days={monthDays} monthLabel={currentMonth} selectedDateKey={selectedDateKey} onSelectDate={setSelectedDateKey} />
        ) : null}
        {view === 'week' ? (
          <WeekView days={weekDays} selectedDateKey={selectedDateKey} onSelectDate={setSelectedDateKey} />
        ) : null}
        {view === 'day' ? (
          <DayView date={selectedDate} encounters={selectedEncounters} onReviewVisit={onReviewVisit} />
        ) : null}
        {view === 'all' ? null : (
          <VisitDetailsPanel
            date={selectedDate}
            encounters={selectedEncounters}
            totalVisits={datedEncounters.length}
            onReviewVisit={onReviewVisit}
          />
        )}
      </div>
    </section>
  );
}

function AllVisitsView({
  encounters,
  onReviewVisit,
  onSelectEncounter,
}: {
  encounters: EncounterItem[];
  onReviewVisit?: (encounter: EncounterItem) => void;
  onSelectEncounter: (encounter: EncounterItem) => void;
}) {
  return (
    <div className="af-visit-all-view" aria-label="All visit history">
      <div className="af-visit-all-view__header">
        <div>
          <h3>All Visit History</h3>
          <p>{encounters.length} visits and documents</p>
        </div>
      </div>
      <ol>
        {encounters.map((encounter) => (
          <li key={encounter.id}>
            <button className="af-visit-all-view__jump" type="button" onClick={() => onSelectEncounter(encounter)}>
              <time dateTime={encounter.startDate}>{formatEncounterDate(encounter.startDate)}</time>
              <span>
                <strong>{encounter.title}</strong>
                <small>{encounter.detail}</small>
                <em>{[encounter.provider, encounter.status].filter(Boolean).join(' - ')}</em>
              </span>
            </button>
            {canReviewVisit(encounter, onReviewVisit) ? (
              <button className="af-visit-review-button" type="button" onClick={() => onReviewVisit(encounter)}>
                {reviewActionLabel(encounter)}
              </button>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );
}

function MonthView({
  days,
  monthLabel,
  selectedDateKey,
  onSelectDate,
}: {
  days: CalendarDay[];
  monthLabel: string;
  selectedDateKey: string;
  onSelectDate: (dateKey: string) => void;
}) {
  return (
    <div className="af-visit-calendar" role="grid" aria-label={`${monthLabel} encounters`}>
      <WeekdayHeader />
      {days.map((day) => (
        <CalendarDayButton day={day} key={day.key} selected={day.key === selectedDateKey} onSelectDate={onSelectDate} />
      ))}
    </div>
  );
}

function WeekView({
  days,
  selectedDateKey,
  onSelectDate,
}: {
  days: CalendarDay[];
  selectedDateKey: string;
  onSelectDate: (dateKey: string) => void;
}) {
  return (
    <div className="af-visit-calendar af-visit-calendar--week" role="grid" aria-label="Week encounters">
      <WeekdayHeader />
      {days.map((day) => (
        <CalendarDayButton day={day} key={day.key} selected={day.key === selectedDateKey} onSelectDate={onSelectDate} />
      ))}
    </div>
  );
}

function DayView({
  date,
  encounters,
  onReviewVisit,
}: {
  date: Date;
  encounters: EncounterItem[];
  onReviewVisit?: (encounter: EncounterItem) => void;
}) {
  return (
    <div className="af-visit-day-view" aria-label={`${longDateLabel(date)} visits`}>
      <div className="af-visit-day-view__date">
        <span>{date.toLocaleDateString(undefined, { weekday: 'long' })}</span>
        <strong>{longDateLabel(date)}</strong>
      </div>
      <VisitTimeline encounters={encounters} emptyMessage="No visits recorded for this day." onReviewVisit={onReviewVisit} />
    </div>
  );
}

function WeekdayHeader() {
  return (
    <>
      {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((day) => (
        <div className="af-visit-calendar__weekday" key={day} role="columnheader">{day}</div>
      ))}
    </>
  );
}

function CalendarDayButton({
  day,
  selected,
  onSelectDate,
}: {
  day: CalendarDay;
  selected: boolean;
  onSelectDate: (dateKey: string) => void;
}) {
  return (
    <button
      aria-pressed={selected}
      className={[
        'af-visit-calendar__day',
        day.inMonth ? '' : 'af-visit-calendar__day--muted',
        day.isToday ? 'af-visit-calendar__day--today' : '',
        selected ? 'af-visit-calendar__day--selected' : '',
        day.encounters.length ? 'af-visit-calendar__day--has-visit' : '',
      ].filter(Boolean).join(' ')}
      onClick={() => onSelectDate(day.key)}
      type="button"
    >
      <span className="af-visit-calendar__date">{day.label}</span>
      {day.encounters.slice(0, 2).map((encounter) => (
        <span className="af-visit-calendar__chip" key={encounter.id}>{encounter.title}</span>
      ))}
      {day.encounters.length > 2 ? <span className="af-visit-calendar__more">+{day.encounters.length - 2}</span> : null}
    </button>
  );
}

function VisitDetailsPanel({
  date,
  encounters,
  totalVisits,
  onReviewVisit,
}: {
  date: Date;
  encounters: EncounterItem[];
  totalVisits: number;
  onReviewVisit?: (encounter: EncounterItem) => void;
}) {
  return (
    <aside className="af-visit-list" aria-label="Selected day visit information">
      <div className="af-visit-list__header">
        <div>
          <h3>{encounters.length ? `Visits on ${shortDateLabel(date)}` : shortDateLabel(date)}</h3>
          <p>{encounters.length ? 'Selected day details' : `${totalVisits} visits in history`}</p>
        </div>
        <span>{encounters.length}</span>
      </div>
      <VisitTimeline
        encounters={encounters}
        emptyMessage="Select a highlighted day to review visit information."
        onReviewVisit={onReviewVisit}
      />
    </aside>
  );
}

function VisitTimeline({
  encounters,
  emptyMessage,
  onReviewVisit,
}: {
  encounters: EncounterItem[];
  emptyMessage: string;
  onReviewVisit?: (encounter: EncounterItem) => void;
}) {
  if (!encounters.length) {
    return <div className="af-visit-list__empty">{emptyMessage}</div>;
  }

  return (
    <ol>
      {encounters.map((encounter) => (
        <li key={encounter.id}>
          <time dateTime={encounter.startDate}>{formatEncounterDate(encounter.startDate)}</time>
          <div>
            <strong>{encounter.title}</strong>
            <p>{encounter.detail}</p>
            <span>{[encounter.provider, encounter.status].filter(Boolean).join(' - ')}</span>
            {canReviewVisit(encounter, onReviewVisit) ? (
              <button className="af-visit-review-button" type="button" onClick={() => onReviewVisit(encounter)}>
                {reviewActionLabel(encounter)}
              </button>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

function canReviewVisit(
  encounter: EncounterItem,
  onReviewVisit: ((encounter: EncounterItem) => void) | undefined
): onReviewVisit is (encounter: EncounterItem) => void {
  return Boolean(onReviewVisit && ((encounter.sourceType === 'encounter' && encounter.encounterId) || (encounter.sourceType === 'document' && encounter.documentId)));
}

function reviewActionLabel(encounter: EncounterItem): string {
  return encounter.sourceType === 'document' ? 'Open document' : 'Review encounter';
}

function EncounterShell({ countLabel, message, tone = 'muted' }: { countLabel: string; message: string; tone?: 'muted' | 'error' }) {
  return (
    <section className="af-visit-history-card" aria-label="Encounter History">
      <div className="af-visit-history-card__header">
        <div>
          <p className="af-dashboard-eyebrow">Encounter Calendar</p>
          <h2>Visit History</h2>
        </div>
        {countLabel ? <span className="af-visit-history-card__count">{countLabel}</span> : null}
      </div>
      <div className={`af-dashboard-card__message af-dashboard-card__message--${tone}`}>{message}</div>
    </section>
  );
}

function groupEncountersByDate(encounters: EncounterItem[]): Map<string, EncounterItem[]> {
  return encounters.reduce<Map<string, EncounterItem[]>>((map, encounter) => {
    const key = encounterDateKey(encounter);
    if (!key) {
      return map;
    }
    const existing = map.get(key) || [];
    existing.push(encounter);
    map.set(key, existing);
    return map;
  }, new Map());
}

function buildCalendarDays(encountersByDate: Map<string, EncounterItem[]>, year: number, month: number): CalendarDay[] {
  const firstOfMonth = monthDate(year, month);
  const start = monthDate(year, month, 1 - firstOfMonth.getDay());
  return Array.from({ length: 42 }, (_, index) => calendarDay(start, index, month, encountersByDate));
}

function buildWeekDays(encountersByDate: Map<string, EncounterItem[]>, selectedDate: Date): CalendarDay[] {
  const start = monthDate(selectedDate.getFullYear(), selectedDate.getMonth(), selectedDate.getDate() - selectedDate.getDay());
  return Array.from({ length: 7 }, (_, index) => calendarDay(start, index, selectedDate.getMonth(), encountersByDate));
}

function calendarDay(start: Date, offset: number, selectedMonth: number, encountersByDate: Map<string, EncounterItem[]>): CalendarDay {
  const date = monthDate(start.getFullYear(), start.getMonth(), start.getDate() + offset);
  const key = dateKey(date);
  return {
    key,
    date,
    label: String(date.getDate()),
    inMonth: date.getMonth() === selectedMonth,
    isToday: key === dateKey(new Date()),
    encounters: encountersByDate.get(key) || [],
  };
}

function encounterDateKey(encounter: EncounterItem): string {
  return (encounter?.startDate || '').slice(0, 10);
}

function dateFromKey(key: string): Date {
  const [year, month, day] = key.split('-').map(Number);
  return monthDate(year, month - 1, day);
}

function shiftDate(date: Date, view: CalendarView, direction: -1 | 1): string {
  if (view === 'day') {
    return dateKey(monthDate(date.getFullYear(), date.getMonth(), date.getDate() + direction));
  }
  if (view === 'week') {
    return dateKey(monthDate(date.getFullYear(), date.getMonth(), date.getDate() + (direction * 7)));
  }
  return dateKey(monthDate(date.getFullYear(), date.getMonth() + direction, 1));
}

function rangeLabel(date: Date, view: CalendarView): string {
  if (view === 'day') {
    return longDateLabel(date);
  }
  if (view === 'week') {
    const start = monthDate(date.getFullYear(), date.getMonth(), date.getDate() - date.getDay());
    const end = monthDate(start.getFullYear(), start.getMonth(), start.getDate() + 6);
    return `${shortDateLabel(start)} - ${shortDateLabel(end)}`;
  }
  return date.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
}

function monthDate(year: number, month: number, day = 1): Date {
  return new Date(year, month, day, 12);
}

function dateKey(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${date.getFullYear()}-${month}-${day}`;
}

function formatEncounterDate(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  const date = match
    ? monthDate(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
    : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return shortDateLabel(date);
}

function normalizeDatedEncounters(encounters: EncounterItem[]): EncounterItem[] {
  return encounters
    .map((encounter) => {
      const fallbackDate = encounter.startDate || encounter.reviewDate || encounter.meta || '';
      return {
        ...encounter,
        startDate: fallbackDate,
        dateSort: encounter.dateSort || (fallbackDate ? Date.parse(fallbackDate) || 0 : 0),
      };
    })
    .filter((encounter) => encounterDateKey(encounter))
    .sort((left, right) => right.dateSort - left.dateSort);
}

function shortDateLabel(date: Date): string {
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function longDateLabel(date: Date): string {
  return date.toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' });
}

function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
