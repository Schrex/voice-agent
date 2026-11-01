# Field Communication

Captures operational needs that foremen phone in to the office and tracks each one to a resolution, so nothing asked for by phone gets lost.

## People

**Foreman**:
A field crew leader, registered on the roster, who calls the office with operational needs for a job.
_Avoid_: Caller, field user, super

**Roster**:
The list of foremen and their registered phone numbers; only rostered numbers may use the assistant.
_Avoid_: Whitelist, directory

**Coordinator**:
An office staff member who answers foreman calls and works the request queue.
_Avoid_: Dispatcher (a dispatcher is an Owner), office user, admin

**Owner**:
The named person or team responsible for fulfilling a request (e.g. dispatch, equipment manager).
_Avoid_: Assignee, handler

**Admin**:
A person who maintains the roster, jobs and contacts.

## Requests

**Request**:
One actionable operational need from a foreman, tied to one job.
_Avoid_: Ticket, message, issue, transcript

**Job**:
A construction job site that requests are made against.
_Avoid_: Project, site

**Category**:
The kind of need a request expresses: Trucking, Equipment, Equipment Repair, Material, Labor, Information, Callback, Other.
_Avoid_: Type, request type

**Callback Request**:
A request, made by the foreman, for a coordinator to call them back.
_Avoid_: Voicemail, message

**Office Line**:
The dedicated office phone number that transfers and emergencies are connected to.
_Avoid_: Main line, ring group

**Transfer**:
Connecting a foreman's call live to the office line at the foreman's request.
_Avoid_: Handoff, escalation

**Emergency**:
A call reporting danger (injury, utility strike, gas, collapse, fire); gets the safety line, an alert to all coordinators, and a transfer to the office line.
_Avoid_: Urgent transfer, escalation

**Urgency**:
How soon a request needs action: Emergency (danger; transferred to the office line), Today, or Planned (tomorrow or later).
_Avoid_: Priority, severity

**Needed-by**:
The date and time the foreman needs the request fulfilled.
_Avoid_: Due date, deadline

## Lifecycle

**Draft**:
A request the foreman did not confirm (hang-up, dropped call, unresolved details); never treated as submitted.

**Recorded**:
A request the foreman confirmed; no human has seen it yet.
_Avoid_: Received, submitted, confirmed

**Acknowledged**:
A coordinator has accepted responsibility for the request and set its owner.
_Avoid_: Assigned, accepted, seen

**In Progress**:
The owner is acting on the request; the outcome is not yet known.

**Resolved**:
The request is finished and carries an outcome and explanation.
_Avoid_: Closed, done, complete

**Outcome**:
How a resolved request ended: Fulfilled, Partially Fulfilled, Denied, or Withdrawn.

**Overdue**:
A request not acknowledged within its acknowledgment window.
_Avoid_: Late, stale

**Foreman Informed**:
A mark that a person has told the foreman the outcome of a resolved request.

**Uninformed**:
A resolved request whose foreman has not been told the outcome within the allowed window.
