"""Read the marks off a figure the way the figure itself was drawn.

Charts state their data in a few distinct ways, and a rule that reads one of
them misreads the others. A scatter plate stamps a glyph per observation, so the
glyphs are the data and there is nothing else to find. A study's time course
stacks all of its series into one column per sampling time, welded together by
error bars, so nothing can be read out of a column directly and the curves have
to be followed into it. A melt curve plots no marks at all - the curve is the
datum - and anything read off it as a mark is an error.

So the figure is asked which of those it is, and it is asked with measurements
rather than a label: does one stamp recur across the plate? do its curves gather
into shared columns? The answer decides which reading is taken, and the answer
is reported alongside the marks so a wrong turn here is visible rather than
buried in the count.
"""
from . import columns
from . import glyphs

# A column reading is only taken where the columns are shared by this many
# curves at once: that is what a sampling time looks like. One or two strands
# gathering is a steep curve, not a schedule.
SHARED_BY = 3


def marks(image_path, plot_bbox):
    """The marks of a figure, read as the figure draws them."""
    stamped = glyphs.find(image_path, plot_bbox)
    # A plate of curves that also stamps a glyph at every sampling time stacks
    # those glyphs into columns welded by their error bars, and reading them as
    # free-standing stamps picks up the welds. Where the figure draws curves and
    # gathers them into shared columns, the curves are followed into the columns
    # instead.
    drawn = (columns.crossing(image_path, plot_bbox) if stamped['marks']
             else SHARED_BY)
    if stamped['marks'] and stamped['stamp_px'] and drawn < SHARED_BY:
        return dict(stamped, drawn_as='a stamp per observation')
    sampled = columns.read(image_path, plot_bbox)
    if (drawn >= SHARED_BY and sampled['series'] >= SHARED_BY
            and sampled['marks']):
        return dict(sampled, drawn_as='series sampled in shared columns',
                    stamp_px=stamped['stamp_px'], pen_px=stamped['pen_px'])
    if stamped['marks']:
        return dict(stamped, drawn_as='marks drawn on the curves')
    return dict(stamped, drawn_as='curves alone, no marks plotted')
