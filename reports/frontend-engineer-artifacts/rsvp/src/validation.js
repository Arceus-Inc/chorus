const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/i;

export const MAX_ATTENDEES = 10;

export function validateName(raw) {
  const value = String(raw ?? '').trim();
  if (!value) return 'Please enter your name.';
  if (value.length < 2) return 'Name must be at least 2 characters.';
  return null;
}

export function validateEmail(raw) {
  const value = String(raw ?? '').trim();
  if (!value) return 'Please enter your email address.';
  if (!EMAIL_RE.test(value)) return 'Please enter a valid email address.';
  return null;
}

export function validateAttendees(raw) {
  const value = String(raw ?? '').trim();
  if (!value) return 'Please enter how many people are attending.';

  const n = Number(value);
  if (!Number.isInteger(n)) return 'Attendee count must be a whole number.';
  if (n < 1 || n > MAX_ATTENDEES) {
    return `Attendee count must be between 1 and ${MAX_ATTENDEES}.`;
  }
  return null;
}

export function validateVegetarian(raw) {
  const value = String(raw ?? '').trim();
  if (value !== 'yes' && value !== 'no') {
    return 'Please choose whether you need a vegetarian meal.';
  }
  return null;
}

export function validateAll(values) {
  const errors = {
    name: validateName(values.name),
    email: validateEmail(values.email),
    attendees: validateAttendees(values.attendees),
    vegetarian: validateVegetarian(values.vegetarian),
  };

  const isValid = Object.values(errors).every((e) => e === null);
  return { errors, isValid };
}

export function normalizeSubmission(values) {
  return {
    name: String(values.name ?? '').trim(),
    email: String(values.email ?? '').trim(),
    attendees: Number(String(values.attendees ?? '').trim()),
    vegetarian: String(values.vegetarian ?? '').trim() === 'yes',
  };
}
