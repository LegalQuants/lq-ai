import { diffWordsWithSpace } from "diff"; // npm install diff

export let docxHelper = {
  /* #region Async Shell Functions */

  /* #endregion */

  /* #region Async Shell Functions */
  async getContextAndWordParagraphs(
    callback: (paras: Word.ParagraphCollection, ctx: Word.RequestContext) => void | Promise<void>
  ) {
    return await Word.run(async (context) => {
      let wparas = context.document.body.paragraphs;
      wparas.load(["text", "isListItem", "listItemOrNullObject", "parentTableOrNullObject"]);
      await context.sync();
      // Both awaited: the previous fire-and-forget `callback(...)` /
      // `context.sync()` (no `await`, no `return`) meant a rejection from
      // either — an async callback's own internal sync failing, or this
      // trailing sync itself — became an unhandled promise rejection with
      // nothing downstream able to catch it.
      await callback(wparas, context);
      await context.sync();
    });
  },

  async getAndWriteContextAndWordParagraphs(
    callback: (paras: Word.ParagraphCollection, ctx: Word.RequestContext) => void
  ) {
    return await Word.run(async (context) => {
      //1: Get original mode
      context.document.load("changeTrackingMode");
      await context.sync();

      //2: Turn off
      const originalMode = context.document.changeTrackingMode;
      context.document.changeTrackingMode = "Off";
      let wparas = context.document.body.paragraphs;
      wparas.load(["text", "isListItem", "listItemOrNullObject", "parentTableOrNullObject"]);
      await context.sync();

      //3: Callback and (changes written to wparas)
      callback(wparas, context);
      context.sync();

      //4: Revert to the original mode
      context.document.changeTrackingMode = originalMode;
      await context.sync();
    });
  },



  /* #endregion */

  async highlightAllWords(text: string, color: string) {
    await Word.run(async (context) => {
      //let t0 = performance.now();
      let paragraphs = context.document.body.paragraphs;
      paragraphs.load(["isEmpty", "paragraphs", "text"]);
      await context.sync();
      let matches = context.document.body.search(text);
      context.load(matches, ["font", "text"]);
      await context.sync();
      for (let match of matches.items) {
        match.font.highlightColor = color;
      }
    });
  },

  async scrollToParagraph(paragraphId: number, text = "") {
    return this.getContextAndWordParagraphs(
      async (wp: Word.ParagraphCollection, ctx: Word.RequestContext) => {
        const paragraph = wp.items.at(paragraphId);
        if (!paragraph) return;

        try {
          if (text.trim().length > 0) {
            const searchResults = paragraph.search(text, { matchCase: false });
            ctx.load(searchResults, "items");
            await ctx.sync();
            if (searchResults.items.length > 0) {
              searchResults.items[0].select();
            } else {
              paragraph.select();
            }
          } else {
            paragraph.select();
          }
          await ctx.sync();
        } catch {
          // The search itself (e.g. RichApi.Error: GeneralException — the
          // quote isn't an exact substring, or Word rejects the search
          // pattern) or the select() it queued failed. The `.select()`
          // calls above only *queue* the operation — they don't execute
          // until a sync, so a failure here can happen either during the
          // search sync or this fallback's own sync; either way, degrade
          // to selecting/scrolling to the whole paragraph rather than
          // leaving the citation click with no visible effect.
          try {
            paragraph.select();
            await ctx.sync();
          } catch {
            // Nothing more we can do without a UI surface to report to —
            // swallow rather than leave an unhandled rejection.
          }
        }
      }
    );
  },


  //! Untested! This is for Skill Application Across the Document.
  async applySurgicalTrackedEdits(
    context: Word.RequestContext,
    paragraph: Word.Paragraph,
    originalText: string,
    newText: string
  ) {
    context.document.changeTrackingMode = Word.ChangeTrackingMode.trackAll;

    const parts = diffWordsWithSpace(originalText, newText);
    // parts: [{ value, added?, removed? }, ...]

    const paraEnd = paragraph.getRange(Word.RangeLocation.end);
    let cursor = paragraph.getRange(Word.RangeLocation.start);

    for (const part of parts) {
      const searchScope = cursor.expandTo(paraEnd); // only the unprocessed remainder

      if (part.removed) {
        const results = searchScope.search(part.value, { matchCase: true });
        const match = results.getFirstOrNullObject();
        match.delete();
        // cursor doesn't advance — the deleted text is gone, next search starts same spot
      } else if (part.added) {
        cursor.insertText(part.value, Word.InsertLocation.before);
        // cursor stays put; inserted text lands right before it
      } else {
        const results = searchScope.search(part.value, { matchCase: true });
        const match = results.getFirstOrNullObject();
        cursor = match.getRange(Word.RangeLocation.after); // advance past unchanged text
      }
    }
  },


};
