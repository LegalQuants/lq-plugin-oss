# United Kingdom — legislation.gov.uk

```json
{
  "code": "UK",
  "name": "United Kingdom",
  "publisher": "legislation.gov.uk",
  "publisher_name": "The National Archives, on behalf of HM Government",
  "consolidated_text": "yes — 'revised', and revision runs behind the law (see below)",
  "authentic_languages": ["English", "Welsh for Acts of Senedd Cymru — both texts equally authentic"],
  "citation_format": "Online Safety Act 2023 (c. 50), s. 12",
  "preferred_url_form": "https://www.legislation.gov.uk/{type}/{year}/{number}  (latest revised)  |  .../enacted  (as enacted)  |  .../{yyyy-mm-dd}  (point in time)",
  "markers": [
    {
      "name": "as-enacted-text",
      "severity": "superseded",
      "pattern": "Status:\\s*This is the original version \\(as it was originally (?:enacted\\)|made\\)(?!\\.?\\s*This item of legislation is currently only available in its original format))",
      "note": "You are on the /enacted page, or for a statutory instrument the /made page. This is the text as passed or made, and it says nothing about what has happened to it since. Refetch the base URL without /enacted or /made."
    },
    {
      "name": "point-in-time-view",
      "severity": "superseded",
      "pattern": "Status:\\s*Point in time view as at\\s+(\\d{2}/\\d{2}/\\d{4})",
      "note": "You are on a dated point-in-time page. It is the text as it stood on the captured date, which is not necessarily the latest revised text, and it can still print the 'up to date' sentence. Refetch the base URL, or record the dated question with --historical-effective and --research-date."
    },
    {
      "name": "provision-prospective",
      "severity": "superseded",
      "pattern": "Status:\\s*(?:Point in time view as at \\d{2}/\\d{2}/\\d{4}\\.\\s*)?This version of this provision is prospective",
      "note": "The publisher marks the version of the provision on this page as prospective: either the provision has never come into force, or this text of it awaits a date for the changes to come into force. It is printed in full and is not the operative text. Do not quote it as operative law. Check its Commencement Information, and state in the note what applies until it comes into force."
    },
    {
      "name": "provision-no-longer-has-effect",
      "severity": "superseded",
      "pattern": "Status:\\s*This version of this provision no longer has effect",
      "note": "The publisher marks the provision on this page as no longer having effect, which generally means that it has been repealed. Read the annotations at the end of the provision. Do not quote it as operative law."
    },
    {
      "name": "provision-repealed-annotation",
      "severity": "superseded",
      "pattern": "Changes to legislation: [^.]{0,200}?, (?:Section|Regulation|Article) (\\d+[A-Z]*)\\b.*?\\bF\\d+ (?-i:S|Reg|Art)\\. \\1 (?:repealed|revoked|omitted)\\b(?!\\s*\\((?:prosp|[ENSW]\\.))",
      "note": "The Textual Amendments on this page record that the provision itself has been repealed, revoked or omitted, and the page shows only what is left in its place. Read the annotation for the date and extent, and do not quote the provision as operative law."
    },
    {
      "name": "changes-yet-to-be-applied",
      "severity": "incomplete",
      "pattern": "Changes and effects yet to be applied to",
      "note": "Effects recorded by the editorial team that are not yet written into the words on this page. If the banner above the list says the item is up to date with all changes known to be in force, a listed effect may be a change not yet in force rather than one missing from the text; otherwise a listed effect may already be in force. Check the commencement of each listed effect that touches a provision relied on."
    },
    {
      "name": "revised-to-date",
      "severity": "info",
      "pattern": "is up to date with all changes known to be in force on or before\\s+(\\d{1,2} [A-Za-z]+ \\d{4})",
      "note": "The revision date. It moves daily, so it is a fact about today's fetch and must be dated in the note."
    },
    {
      "name": "prospective-provisions",
      "severity": "info",
      "pattern": "Status:\\s*This version of this [A-Za-z ]{1,40}?contains provisions that are prospective",
      "note": "Some provisions shown are NOT in force. They are printed in full, tagged 'Prospective' above the heading. Check that tag on any section you quote."
    },
    {
      "name": "revised-may-not-be-current",
      "severity": "info",
      "pattern": "Revised legislation carried on this site may not be fully up to date",
      "note": "The publisher's standing disclaimer on revised text. Carry it into the note when the analysis rests on revised wording."
    }
  ]
}
```

## Revised is not the same as current

legislation.gov.uk will tell you a statute *"is up to date with all changes known
to be in force on or before 23 August 2026"* and, further down the same page,
list under **"Changes and effects yet to be applied"** a set of changes and
effects that are **not** yet applied to the text above.

Both statements are true. Where the banner says the item is up to date with all
changes known to be in force, the text above includes every change the publisher
knows to be in force on that date, so a listed effect may be a change not yet in
force rather than one missing from the text. The editorial team applies
amendments by hand, so where the banner does not say that, a listed effect may
already be in force. The list is on the page.

That is why `changes-yet-to-be-applied` stops the run: check the commencement of
every listed effect that touches a provision relied on before treating the words
you just read as either current or out of date.

## Prospective provisions are printed as though they were law

Where an Act contains provisions not yet commenced, the revised page shows them
in full, in place, with the word **Prospective** on its own line above the
heading. Nothing about the section's own text says it is inert.

This is the UK's version of the recital trap: an ordinary-looking, numbered,
operative-sounding provision that imposes no duty on anyone today. Before
quoting a section, look at the line above its heading.

## Commencement is per-section, and the page tells you

UK Acts commence in pieces, by statutory instrument, sometimes years apart. The
revised text prints the history under each section as **Commencement
Information**:

    I27  S. 17 not in force at Royal Assent, see s. 240(1)
    I28  S. 17 in force at 10.1.2024 by S.I. 2023/1420, reg. 2(e)

Read it. "The Act is in force" is not a fact about an Act; it is a fact about a
section on a date. An answer that treats Royal Assent as the operative date is
wrong more often than it is right.

## Extent

Each provision carries a geographical extent — E, W, S, NI, in any combination —
and they differ within a single Act. A provision that binds in England and Wales
may not bind in Scotland. Where a client operates across the UK, extent is a
question the text answers per section and the note must state.

Devolved legislation is on the same site under its own types: `asp` (Scottish
Parliament), `asc`/`anaw`/`mwa` (Senedd Cymru), `nia` (Northern Ireland
Assembly). Acts of Senedd Cymru are enacted in Welsh and English, both texts
equally authentic.

## URL forms

All five verified against this publisher:

    /ukpga/2023/50                        latest revised text
    /ukpga/2023/50/enacted                as enacted, frozen at Royal Assent
    /ukpga/2023/50/2024-06-01             the text as it stood on that date
    /ukpga/2023/50/section/12             one section
    /ukpga/2023/50/section/12/data.xml    the same section as XML

`{type}` is `ukpga` for a UK Public General Act, `uksi` for a statutory
instrument, plus the devolved types above. Point-in-time addressing is the
answer to "what did this say when the client did the thing" — a question that
comes up constantly in enforcement work and that no secondary source can answer.

## A trap: the page names the versions it is not

Both the revised page and the as-enacted page carry the strings *"Original (As
enacted)"* and *"Original (As Enacted or Made): The original version of the
legislation as it stood when it was enacted or made."* Those are the version
switcher and its help text — they appear whichever version you are looking at.

The only string that actually tells you where you are is the `Status:` line. A
model skim-reading for "as enacted" will conclude it is on the as-enacted page
roughly half the time it is not. This is precisely why the version check is a
regex over saved bytes and not a reading.

## Also worth knowing

- **Correction slips** are the UK analogue of a corrigendum, listed on the page
  under "More Resources" with a date. They correct minor errors that do not
  change the meaning of the legislation (for example a wrong cross-reference)
  without an amending instrument; the correction is made on the website copy,
  not on the original print PDF. A substantive error is corrected by new
  legislation.
- **Statutory instruments carry most of the operative detail.** An Act that says
  the Secretary of State "may by regulations specify" has told you nothing about
  the threshold; the SI has. Find it.
- **Explanatory Notes are not law.** They are useful, they are prepared by the
  government department responsible for the subject matter of the Act, and a
  court may use them to cast light on the meaning of particular provisions, but
  they do not displace the meaning of words that, read in context, are clear and
  unambiguous and do not produce absurdity (R (O) v Secretary of State for the
  Home Department [2022] UKSC 3, para 30). Do not quote them in an operative
  position.
- **Retained/assimilated EU law** still sits under UK law with its own amendment
  history. If the instrument began life in Brussels, check what the Retained EU
  Law (Revocation and Reform) Act 2023 did to it before relying on the text.
