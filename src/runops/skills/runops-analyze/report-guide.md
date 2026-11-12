# Writing a comparison report

Use this when the result of an analysis is a report that someone will read: a comparison
of runs, a parameter dependence, an answer to "what changed and why". The reader was not
there when the runs were made. They should come away knowing what was compared, what
came out, and what it means, without decoding run ids or internal variable names.

[example-report/](example-report/README.md) is a small worked example of everything
below (its data are synthetic). Read it once before writing; copy its
`scripts/build_html.py` into your investigation.

Write in the language the user reads. Fit the number of figures and sections to the
question; nothing here fixes them.

## 1. Order the report so the reader can follow the comparison

1. **Open with the question and the answer.** In a few sentences: what you wanted to
   know, what was held fixed and what was varied, and the main result. A reader who stops
   here still has the conclusion.
2. **Show the setup.** A layout figure or the baseline condition lets the reader picture
   the experiment before any comparison.
3. **Before each figure**, say what the comparison is for and how to read it: what the
   colours, axes, arrows and markers mean, and where to look.
4. **After each figure**, say in connected prose what is visible, how that answers the
   question, and what the figure cannot decide. Lead to the next figure from what this
   one leaves open.
5. **Close with provenance and checks** (sections 3 and 4). Run ids, job ids, variable
   names and version hashes live there, traceable, and the body refers to conditions by
   what they are ("heater 8 cm away"), so the result reads without the internal record.

Write sentences that connect question, observation and interpretation. Compare:

```text
off8: dT=+7.91, dT_ring=-0.11. no hot spot. path not separated.
```

> Even with the heater 8 cm away, the sensor is about 8 K warmer than without it. The
> sensor and its surroundings are then at nearly the same temperature, so the sensor is
> not a hot spot: the distant heater warms it by warming a wide area of the plate. The
> saved field cannot tell whether that heat arrived through the plate or through the air.

The second is not better because it is longer; it is better because the reader does not
have to supply the meaning.

## 2. Show the original fields side by side, then dependences and differences

- The basic comparison figure places the control and the changed conditions next to each
  other as they are. For the same quantity, use the same coordinate range, colour scale,
  unit and time window in every panel, and put the condition name and its key value on
  each panel. Readers see what each state looks like and judge the change themselves.
- After that, add the dependence on the varied parameter (mark the points whose fields
  were shown), and a difference map where the question is about the difference itself
  or the change is too small to see side by side.
- Say what "the data" are: instantaneous or time-averaged (over which window), smoothed
  or masked or neither. Put anything easy to misread next to the figure it concerns:
  blank regions on a log scale, the sign convention of a current, the direction of
  vectors.
- For a figure of a representative value (a mean, a total), state in the text the region
  it averages over, the weighting, and the reference it is measured from (such as the
  zero of a potential).

## 3. State what makes the comparison valid, and where interpretation stops

- Record for every condition: code version, what it was restarted from and how much
  further it ran, the settings in effect, and the averaging window. Check that the runs
  differ only in what the report says they differ in.
- Compare like with like: a run still in progress against the control at the same
  elapsed time, the same averaging window on both sides.
- Design a reproducibility check as separate questions: bitwise agreement, the scatter
  between samples, and a tolerance on the physical quantity you compare. Parallel runs
  may sum in a different order, so they can differ bitwise while agreeing physically.
- Keep what was observed apart from what you infer from it. Name a limit where it
  affects a reading of this result, and say which reading: "density is higher here, but
  that alone does not show the net current is larger"; "streamlines of the mean flow are
  not single-particle orbits". One specific limit at the place it matters does more
  than a general caution repeated under every figure.

## 4. Deliver the same content as Markdown and as one HTML file

Keep in the investigation directory (layout as in SKILL.md step 3):

- `README.md`: the report, with figures as relative links (`out/fig1.png`). It is the
  entry point in an editor's Markdown preview and the single source of the text.
- `report.html`: built from the README by `scripts/build_html.py`, with every figure
  embedded as a data URI, so the one file can be sent or opened anywhere.
- `out/`: the figure files, and the numbers behind them as CSV or JSON.
- `scripts/`: what regenerates the figures and tables from the runs.

Check three things separately, and record each in a short section at the end of the
report so the checks do not bury the explanation:

1. **Files**: `python scripts/build_html.py --check` confirms `report.html` matches the
   README and reports how many images it embeds.
2. **Figure content**: open each image and confirm that labels, legends and values are
   legible and agree with the tables.
3. **Rendered page**: say whether the HTML was opened in a browser. If it was not, write
   that; a file check is not a display check.
