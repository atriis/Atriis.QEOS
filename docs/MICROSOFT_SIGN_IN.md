# Microsoft sign-in: setup guide

This guide takes a QEOS deployment from password-only sign-in to sign-in with Microsoft work
accounts (Entra ID). Optionally, Entra can also set each person's organization role, and QEOS can
be made Microsoft-only.

It is the step-by-step companion of [SETUP section 3.8](SETUP.md#38-single-sign-on-google-and-microsoft),
which remains the reference. Decisions: ADR-031 (SSO-only mode), ADR-033 (Entra app roles).

## Contents

1. [How it works](#1-how-it-works)
2. [Before you start](#2-before-you-start)
3. [Step 1: the app registration (IT)](#3-step-1-the-app-registration-it)
4. [Step 2: configure QEOS](#4-step-2-configure-qeos)
5. [Step 3: test the sign-in](#5-step-3-test-the-sign-in)
6. [Step 4 (optional): organization roles from Entra](#6-step-4-optional-organization-roles-from-entra)
7. [Step 5 (optional): Microsoft-only sign-in](#7-step-5-optional-microsoft-only-sign-in)
8. [Day-to-day operations](#8-day-to-day-operations)
9. [Troubleshooting](#9-troubleshooting)
10. [Appendix: request to send to IT](#10-appendix-request-to-send-to-it)

---

## 1. How it works

```
 Browser (dashboard)                Entra ID                     auth-service
 ───────────────────                ────────                     ────────────
 "Sign in with Microsoft" ───────►  popup: sign-in, MFA
                          ◄───────  ID token (oid, tid, UPN, roles)
 POST /api/v1/sso/microsoft ──────────────────────────────────►  checks signature, audience,
                                                                 tenant allowlist, issuer
                          ◄──────────────────────────────────── QEOS session (cookie)
```

- The dashboard uses MSAL in a **popup** with the scopes `openid profile email`. It needs no client
  secret: a single-page application is a public client.
- auth-service checks the ID token: its signature (Microsoft's published keys), the audience (your
  client id), the issuer, and that the tenant (`tid`) is on the allowlist.
- The account address is the user principal name (`preferred_username`). The `email` claim is used
  only when Microsoft vouches for its domain (`xms_edov`), because a tenant administrator can set
  `email` to any value.
- Microsoft's MFA protects the sign-in. QEOS two-factor authentication applies to password sign-in
  only.
- Personal Microsoft accounts (outlook.com, hotmail.com) are not supported.

The same client id is configured in **two places**, for two different jobs:

| Where | Setting | Job |
|---|---|---|
| Dashboard (baked in at build time) | `VITE_MSAL_CLIENT_ID` | Shows the button and gets the token |
| auth-service (read at start) | `AZURE_CLIENT_ID` | Checks that the token was issued for QEOS |

If only the first is set, the button shows but sign-in answers **503**.

## 2. Before you start

You need:

- A running QEOS stack ([SETUP section 2](SETUP.md#2-first-time-setup)) and its address, for
  example `https://localhost:8443` locally or `https://qeos.example.com` in production.
- A QEOS **superuser** with a password. Keep it: it is the break-glass account if Microsoft
  sign-in fails.
- Someone who can create an app registration in your Entra tenant. By default every user can, but
  many companies turn that off. If **App registrations → New registration** is greyed out for you,
  ask IT. The [appendix](#10-appendix-request-to-send-to-it) has a ready-to-send request.

Names used in this guide:

| QEOS setting | Azure portal name | Where to find it |
|---|---|---|
| `VITE_MSAL_CLIENT_ID`, `AZURE_CLIENT_ID` | Application (client) ID | App registrations → the app → Overview |
| `AZURE_ALLOWED_TENANTS` | Directory (tenant) ID | Microsoft Entra ID → Overview, or the app's Overview |

The tenant id is a GUID such as `72f988bf-86f1-41af-91ab-2d7cd011db47`, not a domain name. Do not
confuse the client id with the app's **Object ID**, a different value on the same page.

## 3. Step 1: the app registration (IT)

In the [Azure portal](https://portal.azure.com):

1. Open **Microsoft Entra ID → App registrations → New registration**.
   - **Name:** `QEOS` (or `QEOS Local` for a test stack).
   - **Supported account types:** *Accounts in this organizational directory only* (single tenant).
   - **Redirect URI:** platform **Single-page application (SPA)**, value = the address of QEOS,
     exactly as people open it, with the port and without a trailing slash. Example:
     `https://localhost:8443`.
2. Open **Authentication**.
   - Add every other address QEOS is opened at (local, staging, production) as an extra SPA
     redirect URI.
   - Under *Implicit grant and hybrid flows*, tick **ID tokens**.
   - Do not choose the **Web** platform: MSAL in the browser needs **SPA**.
3. Open **API permissions**. Microsoft Graph `User.Read` is there by default. Add the delegated
   permissions `openid`, `profile` and `email`, then **Grant admin consent** so people are not asked
   to consent one by one (and are not blocked if your tenant forbids user consent).
4. Recommended: open **Enterprise applications → QEOS → Properties** and set
   **Assignment required** to **Yes**. Then only people or groups assigned to the app can sign in,
   and Entra becomes the gate for who may use QEOS.
5. Copy the **Application (client) ID** and the **Directory (tenant) ID** from the Overview page.

No client secret and no certificate are needed.

## 4. Step 2: configure QEOS

Add to `.env` (next to `docker-compose.yml`):

```dotenv
# Microsoft sign-in
VITE_MSAL_CLIENT_ID=<Application (client) ID>
AZURE_CLIENT_ID=<the same Application (client) ID>
AZURE_ALLOWED_TENANTS=<Directory (tenant) ID>
# Recommended for a single tenant: sign-in goes straight to your company's page
VITE_MSAL_AUTHORITY=https://login.microsoftonline.com/<Directory (tenant) ID>
```

| Setting | Default | Notes |
|---|---|---|
| `VITE_MSAL_CLIENT_ID` | empty | Empty hides the Microsoft button. Build-time value. |
| `VITE_MSAL_AUTHORITY` | `https://login.microsoftonline.com/organizations` | Any work account; the tenant allowlist still decides. Build-time value. |
| `AZURE_CLIENT_ID` | empty | Must equal `VITE_MSAL_CLIENT_ID`. |
| `AZURE_ALLOWED_TENANTS` | empty | Comma-separated tenant ids. Empty falls back to `AZURE_TENANT_ID`. List only tenants you fully trust (see [section 6](#trust-between-tenants)). |

Then rebuild and restart:

```bash
docker compose up -d --build --wait gateway
```

`--build` matters: the `VITE_*` values are baked into the dashboard when it is built. Setting them
without rebuilding changes nothing.

## 5. Step 3: test the sign-in

1. Open QEOS in a private window. The sign-in page shows **Sign in with Microsoft**.
2. Sign in with a work account. If the browser blocks the popup, allow popups for the QEOS address.
3. You land on the project list. The first Microsoft sign-in with a new address creates an account
   without a password.
4. Check the log: `docker compose logs auth-service | grep -i microsoft` shows no
   "not configured" and no "refused".

**Existing accounts are not linked automatically.** If the address already has a QEOS password
account, the sign-in answers 409. The person signs in with their password, then links Microsoft:
account menu → **Security** → **Microsoft account** → **Link Microsoft account**. Addresses match
whatever their letter case.

## 6. Step 4 (optional): organization roles from Entra

With this step, Entra decides each person's role in a QEOS organization (ADR-033). New colleagues
join with the right role at their first sign-in, and role changes follow the directory.

### In Entra (IT)

1. On the app registration, open **App roles → Create app role** three times:

   | Display name | Allowed member types | Value |
   |---|---|---|
   | QEOS Admin | Users/Groups | `QEOS.Admin` |
   | QEOS Member | Users/Groups | `QEOS.Member` |
   | QEOS Viewer | Users/Groups | `QEOS.Viewer` |

2. Open **Enterprise applications → QEOS → Users and groups → Add user/group**, then pick people
   or groups and a role. Assigning **groups** needs Entra ID P1 or P2. Assigning individual users
   works on every tier.

No token configuration or optional claim is needed: the `roles` claim is in the ID token by default.

### In QEOS (organization owner)

Open the **Organization** page → **Microsoft roles**, and map each value:

| Entra value | QEOS role |
|---|---|
| `QEOS.Admin` | admin |
| `QEOS.Member` | member |
| `QEOS.Viewer` | viewer |

Mappings belong to one organization. Two organizations may map the same value differently. Values
match whatever their letter case.

### The rules

- A mapping grants **admin**, **member** or **viewer**. It never grants **owner**: owners are
  always added by hand.
- Members that Entra created carry an **Entra** badge. At each Microsoft sign-in, their role follows
  Entra, and a member with no matching role any more is removed.
- Members invited by hand are never changed by Entra.
- With several app roles, the highest mapped role wins: admin, then member, then viewer.
- A change in Entra takes effect at the person's **next Microsoft sign-in**. A session they already
  hold keeps working until it ends (see [section 8](#8-day-to-day-operations)).
- Removing a mapping in QEOS changes nobody until their next sign-in.
- Outside Microsoft-only mode, a linked person who signs in with a password is not reconciled at
  that sign-in.
- If organization-service is down at a sign-in, the sign-in still works, and auth-service applies
  the roles at the next token refresh (within the hour) or the next sign-in.

`docker-compose.yml` already gives auth-service what it needs (`ORGANIZATION_SERVICE_URL`, and your
`INTERNAL_API_PASSWORD`). On AKS or another deployment, pass `ORGANIZATION_SERVICE_URL` and
`ORGANIZATION_INTERNAL_API_PASSWORD` to auth-service and `INTERNAL_API_PASSWORD` to
organization-service. Without them, auth-service logs a WARNING at start and applies no role.

### Trust between tenants

A mapping does not name a tenant. If `AZURE_ALLOWED_TENANTS` lists several tenants, an administrator
of **any** of them can grant every mapped role in every organization that maps that value. With one
tenant this does not matter. Add a second tenant only if you trust its administrators that much.

## 7. Step 5 (optional): Microsoft-only sign-in

For a company deployment where people sign in only with their work account (ADR-031). Passwords stay
for superusers only, as break-glass.

1. Finish steps 1-3 and check that Microsoft sign-in works.
2. Ask everyone with a password account to link Microsoft (account menu → **Security** →
   **Microsoft account** → **Link Microsoft account**).
3. As a superuser, open **Security → Microsoft-only sign-in**. It shows "N of M active users have
   linked Microsoft" and lists who has not. For someone who missed it, **Allow link at next
   sign-in** lets that account link at its next Microsoft sign-in, for 7 days.
4. In `.env`:
   ```dotenv
   AUTH_SSO_ONLY=true
   AUTH_SSO_PROVIDERS=microsoft
   ```
   Then `docker compose up -d --wait auth-service`.

What changes at that restart:

- Every session of everyone who is not a superuser ends, once. Access tokens already issued run out
  within 60 minutes.
- Registration, email verification and password recovery answer 403.
- auth-service refuses to start if Microsoft is not configured, and warns in its log when there is
  no active superuser.

**Break-glass:** active superusers keep password sign-in, with two-factor authentication. Each such
sign-in is logged at WARNING:

```bash
docker compose logs auth-service | grep break-glass
```

To turn the mode off: set `AUTH_SSO_ONLY=false` and restart auth-service.

## 8. Day-to-day operations

| Situation | What to do |
|---|---|
| A new colleague joins | Assign them in Entra (with an app role, if you use [step 4](#6-step-4-optional-organization-roles-from-entra)). They sign in once. Without a matching mapping, an owner or admin adds them to the organization. |
| Someone changes role | Change their app role in Entra. It applies at their next Microsoft sign-in. |
| Someone leaves | Remove or disable them in Entra **and deactivate them in QEOS**. See the limitation below. |
| Someone already had a password account | They link Microsoft under **Security**, or a superuser uses **Allow link at next sign-in**. |
| New QEOS address (new server, new port) | Add it to the app registration as an SPA redirect URI. |

**Known limitation.** A person removed from Entra cannot get a new Microsoft token, but a QEOS
session they already hold lasts until its refresh token expires (30 days). Deactivate them in QEOS
to end it at once. Automatic deprovisioning (SCIM) is not built.

## 9. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| No Microsoft button | `VITE_MSAL_CLIENT_ID` was set after the build. Run `docker compose up -d --build --wait gateway`. |
| Button shows, sign-in answers 503 | auth-service lacks `AZURE_CLIENT_ID` or `AZURE_ALLOWED_TENANTS`. Set them in `.env` and recreate auth-service. |
| Popup closes at once, or nothing happens | The browser blocked the popup. Allow popups for the QEOS address. |
| `AADSTS50011` (redirect URI mismatch) | The address in the browser is not an SPA redirect URI of the app. Add it exactly: scheme, host and port. |
| `AADSTS9002326` (cross-origin token redemption) | The redirect URI is under the **Web** platform. Move it to **Single-page application**. |
| `AADSTS50105` (user not assigned) | **Assignment required** is on and the person is not assigned. Assign them under Enterprise applications → Users and groups. |
| `AADSTS65001` (consent required) | Admin consent was not granted. IT grants it under API permissions. |
| Sign-in refused, log says `tenant … is not in AZURE_ALLOWED_TENANTS` | The account belongs to another tenant (or is a guest's home tenant). The log line names the tenant id. Add it only if you trust that tenant. |
| 409 at sign-in | An account with that address already exists. Link Microsoft from **Security**, or ask a superuser for **Allow link at next sign-in**. |
| "Microsoft account has no email address" | The account has no user principal name on a verified domain. Ask IT. |
| Role from Entra not applied | Check the mapping on **Organization → Microsoft roles**, that the person is assigned that app role, and that they signed in again after the change. Members invited by hand are never changed. |
| auth-service exits with "AUTH_SSO_ONLY=true but …" | A provider in `AUTH_SSO_PROVIDERS` is not configured. The log names the missing setting. |

More: the common problems table at the end of [SETUP section 3.8](SETUP.md#38-single-sign-on-google-and-microsoft).

## 10. Appendix: request to send to IT

> **Subject:** Entra app registration for QEOS (Microsoft sign-in)
>
> Hello,
>
> Please create an app registration so colleagues can sign in to QEOS, our QA platform, with their
> Microsoft work account.
>
> **App registration**
> - Name: QEOS
> - Supported account types: this organization only (single tenant)
> - Platform: Single-page application (SPA), with ID tokens enabled
> - Redirect URIs: `https://localhost:8443` (and later the production address: `<to be confirmed>`)
> - API permissions: Microsoft Graph delegated `openid`, `profile`, `email`, with admin consent
> - No client secret is needed
>
> **App roles** (allowed member types: Users/Groups)
> - `QEOS.Admin`, `QEOS.Member`, `QEOS.Viewer`
>
> **Enterprise application**
> - Assignment required: Yes
> - Assign: `<names or groups>` with the role `<role>` (groups if our tenant has Entra ID P1/P2)
>
> **Please send back**
> - Application (client) ID
> - Directory (tenant) ID
>
> When someone leaves, please also tell the QEOS administrators, so they can deactivate the account
> in QEOS.
>
> Thank you.
