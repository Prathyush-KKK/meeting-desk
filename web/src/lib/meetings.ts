import type { MeetingItem } from "@/api/types";

/** A calendar card has no row yet, so it is keyed on the event id until it is captured. */
export function itemKey(item: MeetingItem): string {
  return item.id ?? `event:${item.calendar_event_id ?? item.ical_uid ?? item.title}`;
}
