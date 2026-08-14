# These are readability rules, not AI-detection rules

Read the check list and you will see bans on `the honest part`, on hedges like
`clearly` and `arguably`, on stacked headings, and on burying the conclusion.
Those look like the tells people cite when accusing a text of being
machine-written. They are not, and the difference matters enough to state
plainly.

**Every rule here predates large language models by decades, and every one is
defended on the same ground: a reader should get it in a single pass.**

## The clarity index is Gunning's Fog Index without the scaling

The formula this repository enforces comes from DA Pam 600-67, *Effective
Writing for Army Leaders*, published 1986. It reads:

    clarity index = average sentence length + percentage of words of 3+ syllables
    aim 30, band 20 to 40

Robert Gunning published the Fog Index in 1952:

    Fog = 0.4 x (average sentence length + percentage of complex words)

Complex means three or more syllables. The Army index is Gunning's formula with
the 0.4 dropped. An index of 30 is a Fog of 12, which is the reading level of a
high-school senior. An index over 40 is a Fog over 16, meaning a reader needs a
university degree to follow it in one pass.

Rudolf Flesch published Reading Ease in 1948, on the same two variables, sentence
length and syllable count, originally for the US Navy.

So the measurement is 74 years old, was built for the military and for business
writing, and was aimed at readers in a hurry. It was not built to catch anything.

## Why the specific bans are readability rules

**Bottom line first.** Newspapers called it the inverted pyramid long before
anyone wrote a style guide about it. The reader stops when they have enough, so
what they need goes where they stop. DA Pam 600-67 para 3-2a states it as the
first structural rule.

**Short sentences and short words.** These are the two variables in every
readability formula since 1948. Not a style preference: the measured inputs.

**No hedging adverbs.** `Clearly`, `obviously`, `arguably` assert a confidence
the sentence has not earned. Cutting them is not about sounding less like a
model. It is about not claiming what you cannot show, which is the same standard
this project applies to a benchmark or a study.

**No `the honest part`, no `this is the part`.** These spend a clause announcing
that a point is coming, then make the point. That is one clause of delay per
occurrence, paid by every reader. The same objection applies to "it should be
noted that" and "at the end of the day", which no one associates with machines.

**No stacked headings.** A heading is a promise of a new subject. Four headings
on one change asks the reader to hold four subjects that turn out to be one.

## Where an AI-detection rule would differ

An AI-detection rule optimises for a *signal*, so it targets whatever is
currently distinctive: a particular word, a punctuation habit, a rhythm. It goes
stale the moment models change, and it produces false accusations against people
who happen to write that way.

A readability rule optimises for the *reader*. It does not care who wrote the
text. It makes the same demand of a memo written in 1986, a commit message
written today, and a draft written by an agent.

Test it this way: if a rule here would still be worth following in a world with
no language models at all, it belongs. Every rule in this repository passes that
test. Any rule that fails it should be removed, and pull requests saying so are
welcome.

## The one thing that is genuinely about agents

The observation that produced this repository is about agents, and it is stated
as an observation rather than a finding:

> Rules with an operation get followed. Rules stated as advice get lost.

An agent given "count the em dashes" obeys for weeks. The same agent given "put
the bottom line first" breaks it repeatedly, because there is nothing to run.
That is why the rules here ship as a script and a hook rather than as a style
guide.

That claim rests on one operator watching one agent over several weeks. It is
not a study, and it is not offered as one.

## Sources

- DA Pam 600-67, *Effective Writing for Army Leaders*, HQDA, 02 June 1986. US
  federal work, public domain under 17 USC 105.
  <https://www.armywriter.com/DAP600-67.pdf>
- Robert Gunning, *The Technique of Clear Writing*, 1952, which introduced the
  Fog Index.
- Rudolf Flesch, Reading Ease, 1948.

The two book citations are given from secondary sources and have not been
checked against the originals. Anyone using this repository for an argument that
turns on them should verify them first.
