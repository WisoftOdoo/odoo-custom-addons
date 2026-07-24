# Brokerage Telephony Integration

## Architecture

Brokerage CRM stores a provider-neutral call session. A configured adapter
starts the call, while PBX events or final CDR data update the same session.

The current outbound adapters are:

- **Generic HTTP PBX**: calls any middleware or PBX endpoint that implements
  the normalized request contract below.
- **3CX Call Control**: obtains an OAuth client-credentials token and invokes
  the 3CX `makecall` endpoint.

Future PBX adapters can extend `_adapter_method_map()` without changing
`crm.lead`, SLA, Round Robin, or contact-attempt logic.

## CRM behavior

1. The assigned salesperson opens a CRM lead and clicks **Call Customer**.
2. Odoo creates a call reference and asks the PBX to initiate the call.
3. The salesperson's registered PBX desk/mobile device rings first.
4. After the salesperson answers, the PBX calls the customer.
5. PBX events/CDR data update ring, talk, and total duration.
6. The salesperson still uses **Record Contact Attempt** to record the
   business result.

An answered or completed technical call does **not** automatically move a
lead, stop SLA, or count as successful customer contact.

## Configuration

### Provider

Go to:

`CRM > Configuration > Brokerage Configuration > Telephony > Providers`

Configure:

- unique Provider Code;
- adapter type;
- HTTPS PBX/bridge URL;
- outbound credentials;
- inbound webhook token;
- connection, response, and call timeouts.

Then select the provider in:

`CRM > Configuration > Settings > Brokerage Telephony`

### User

Go to the Odoo user and open **Brokerage Telephony**:

- **Telephony Provider Override**: optional; otherwise the company default is
  used;
- **PBX Extension**: required;
- **PBX Device ID**: optional. For 3CX, use it when the extension has multiple
  registered devices and a particular desk/mobile device must ring.

## Generic HTTP outbound request

Odoo sends:

```json
{
  "request_id": "odoo-generated-uuid",
  "provider_code": "office-pbx",
  "direction": "outgoing",
  "agent": {
    "odoo_user_id": 10,
    "extension": "123",
    "device_id": "optional-device-id"
  },
  "customer": {
    "odoo_lead_id": 25,
    "phone": "+971501234567"
  },
  "callback": {
    "url": "https://odoo.example.com/brokerage/api/v1/telephony/events/office-pbx",
    "header": "X-Brokerage-Telephony-Token"
  },
  "timeout_seconds": 30
}
```

The PBX/bridge should return:

```json
{
  "external_call_id": "PBX-CALL-123",
  "status": "ringing"
}
```

## Inbound event/CDR API

Endpoint:

`POST /brokerage/api/v1/telephony/events/{provider_code}`

Headers:

```text
Content-Type: application/json
X-Odoo-Database: your_database
X-Brokerage-Telephony-Token: provider_webhook_token
```

Completed event example:

```json
{
  "event_id": "PBX-EVENT-987",
  "request_id": "odoo-generated-uuid",
  "external_call_id": "PBX-CALL-123",
  "parent_call_id": "PBX-CALL-FLOW-100",
  "status": "completed",
  "started_at": "2026-07-24T09:00:00Z",
  "answered_at": "2026-07-24T09:00:04Z",
  "ended_at": "2026-07-24T09:00:34Z",
  "ring_duration_seconds": 4,
  "talk_duration_seconds": 30,
  "total_duration_seconds": 34,
  "termination_reason": "remote_hangup",
  "recording_url": "https://pbx.example.com/recordings/call-123"
}
```

Supported states are:

- `initiated`
- `ringing`
- `answered`
- `completed`
- `missed`
- `failed`
- `cancelled`

Every event needs a globally unique `event_id` for its provider. Repeating an
event is safe and returns `"duplicate": true`. Concurrent delivery of the same
event is serialized before processing.

For a PBX-created incoming or externally initiated call with no Odoo
`request_id`, send:

- `external_call_id`;
- `agent_extension`;
- `direction`;
- `from_number` and `to_number`;
- optional `lead_id`.

## 3CX

The direct adapter uses:

- `POST /connect/token`
- `POST /callcontrol/{extension}/makecall`, or
- `POST /callcontrol/{extension}/devices/{device_id}/makecall`

Configure a 3CX API client with Call Control access and store its Client ID and
API key only in the provider configuration. Do not put credentials in source
code.

3CX Call Control initiates calls. Final duration should be sent from 3CX
CDR/call journaling to the normalized event endpoint, using the PBX call
history/call identifier as `external_call_id` or `parent_call_id`.

## Security

- Provider secrets are restricted to Odoo system administrators.
- The webhook requires a constant-time-checked token.
- Provider codes are unique.
- Production URLs require HTTPS.
- Agents can read only their own call history.
- Sales Managers can read all Brokerage call history.
- Raw provider payloads are retained in the Telephony Event Log for audit.
