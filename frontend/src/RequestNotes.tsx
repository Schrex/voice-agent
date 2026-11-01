import { officeTime, type RequestNote } from "./api";

/** The request's notes (ticket #17), oldest first; an urgent one carries an "Urgent" marker. */
export function RequestNotes({ notes }: { notes: RequestNote[] }) {
  return (
    <>
      <h2 id="notes">Notes</h2>
      {notes.length === 0 ? (
        <p>No notes.</p>
      ) : (
        <ul className="notes" aria-labelledby="notes">
          {notes.map((note, i) => (
            <li key={i}>
              <time dateTime={note.at}>{officeTime.format(new Date(note.at))}</time>{" "}
              {author(note)}
              {note.urgent && (
                <>
                  {" "}
                  <span className="flag">Urgent</span>
                </>
              )}
              <p>{note.text}</p>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function author(note: RequestNote): string {
  if (note.author_type === "agent") return "Agent";
  if (note.author_type === "system") return "System";
  return note.author ?? "Staff";
}
