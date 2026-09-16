const RFC3339 =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|([+-])(\d{2}):(\d{2}))$/;
const MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

function numberGroup(match: RegExpMatchArray, index: number): number {
  const value = match[index];
  return value === undefined ? Number.NaN : Number(value);
}

function isLeapYear(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

export function isValidRfc3339(value: string): boolean {
  const match = value.match(RFC3339);
  if (match === null) {
    return false;
  }
  const year = numberGroup(match, 1);
  const month = numberGroup(match, 2);
  const day = numberGroup(match, 3);
  const hour = numberGroup(match, 4);
  const minute = numberGroup(match, 5);
  const second = numberGroup(match, 6);
  const ordinaryMonthDays = MONTH_DAYS[month - 1] ?? 0;
  const daysInMonth =
    month === 2 && isLeapYear(year) ? ordinaryMonthDays + 1 : ordinaryMonthDays;
  const calendarValid =
    year >= 1 &&
    month >= 1 &&
    month <= 12 &&
    day >= 1 &&
    day <= daysInMonth &&
    hour >= 0 &&
    hour <= 23 &&
    minute >= 0 &&
    minute <= 59 &&
    second >= 0 &&
    second <= 59;
  if (!calendarValid || match[8] === "Z") {
    return calendarValid;
  }
  const offsetHour = numberGroup(match, 10);
  const offsetMinute = numberGroup(match, 11);
  return offsetHour <= 23 && offsetMinute <= 59;
}
