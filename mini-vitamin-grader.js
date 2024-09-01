/* ALL CREDITS FOR THIS SCRIPT GO TO CS161 https://github.com/cs161-staff/gradescope-autoselect/blob/main/select-all.js 

   This script has been adapted for the purposes of CS70 mini vitamins with slight modifications in terms of 
   having no "None of the above" answer choices and fixing the grading logic accordingly
*/

// Copy paste this first into inspect element console.

/*
 * Returns an array of booleans such that the ith rubric item corresponds to
 * whether the ith rubric item should be selected for the currently viewed
 * submission.
 *
 * The current implementation uses ANS_MASK such that ANS_MASK[i] is 1 if
 * selectin answer choice i was a correct answer and 0 if leaving it unselected
 * was a correct answer.
 *
 * It will return an array of length ANS_MASK.length + 1, assuming that the
 * (ANS_MASK.length)'th rubric item is an "Incorrect/blank" rubric item so that
 * Gradescope marks the submission as graded. It assumes an additive rubric, so
 * the rubric item will be marked if answer is correct.
 *
 * It also assumes that "None of the above" is the (ANS_MASK.length)'th answer
 * choice. If "None of the above" and something else are selected, no points are
 * received. If "None of the above" is selected by itself, grading proceeds as
 * if no answer choices were selected. If everything is blank, no points are
 * received.
 */
function score() {
  const ANS_MASK = []; // EDIT THIS LIST

  const checkboxes = Array.from(
    document.querySelectorAll("[id^='question_'] input[type='checkbox']"),
  );
  const marked = checkboxes.map((e) => e.checked);

  let ret;
  if (!marked.some((e) => e)) {
    /* No marked boxes. Incorrect/blank. */
    ret = new Array(ANS_MASK.length);
    ret.fill(false);
    ret.push(true);
  } else {
    /* Something was marked. */
    ret = ANS_MASK.map((solution, i) => solution == marked[i]);
    /* If all rubric items are marked false, push true at the end for
     * Incorrect/blank, else push false. */
    ret.push(ret.every((e) => !e));
  }
  return ret;
}

// Run score() on console to see if it produces the correct grade.

// Next, copy paste this into the console.

/*
 * Grades the current submission based on the return value of score().
 */
function grade() {
  let scoredRubric = score();
  let rubric = document.querySelectorAll(".rubricItem--key");
  for (let i = 0; i < scoredRubric.length; i++) {
    // Apply the item rubric[i] if scoredRubric[i] is true.
    if (scoredRubric[i]) {
      rubric[i].click();
    }
  }
}

// Run grade() on console to see if the correct choice is selected.

// If it works, paste this input into the console to start the autograding
// procedure.

{
  let href = window.location.href;
  let nextGraded = document.querySelector('[title="Shortcut: Z"]');
  let justGraded = false;
  setInterval(() => {
    /* Alternate between grading & clicking next to give some time to update the grade. */
    if (justGraded) {
      justGraded = false;
      /* Go to next ungraded. */
      nextGraded.click();
    } else {
      /* Wait for updated URL. */
      if (href != window.location.href) {
        href = window.location.href;
        /* Grade the submission. */
        grade();
        justGraded = true;
      }
    }
  }, 100);
  grade();
  nextGraded.click();
}
