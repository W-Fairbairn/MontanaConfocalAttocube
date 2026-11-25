import time
import numpy as np
from qudi.interface.timetagger_interface import TimeTaggerInterface
from qudi.core.configoption import ConfigOption
import TimeTagger




class SwabianTimeTagger(TimeTaggerInterface):
    binwidth = ConfigOption(name="binwidth", default=800)
    number_of_bins = ConfigOption(name="number_of_bins", default=5000)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def on_activate(self):
        # Set channel number scheme to suppress deprecation warning
        TimeTagger.setTimeTaggerChannelNumberScheme(TimeTagger.TT_CHANNEL_NUMBER_SCHEME_ONE)
        #connect to tagger
        self.tagger = self.connect_tagger()
        self.counter = TimeTagger.Counter(self.tagger, [7, 8], binwidth=self.binwidth, n_values=self.number_of_bins)
        # self.get_counts()
        return True

    def on_deactivate(self):
        TimeTagger.freeTimeTagger(self.tagger)
        return True

    def connect_tagger(self):
        return TimeTagger.createTimeTagger()

    def get_counts(self, avg_time=0):
        """Return the current count rate.

        Previously this always averaged over the entire rolling buffer
        (number_of_bins * binwidth, e.g. a full second with the configured
        defaults), no matter how it was called. That makes every reading a
        heavily lagged/smeared trailing average, which silently defeats any
        caller doing rapid sampling (e.g. a fast z scan) or its own explicit
        multi-sample averaging (several call sites already average a handful
        of get_counts() calls themselves, which only makes sense if each call
        is a fresh, fast reading). Now it only averages the most recent bins
        covering `avg_time` seconds (default: just the latest single bin, i.e.
        as fast/instantaneous as the configured binwidth allows).
        """
        counts = self.counter.getDataNormalized()
        total_counts = counts[0] + counts[1]
        bin_width_s = self.binwidth * 1e-12  # binwidth is in picoseconds
        n_bins = max(1, int(round(avg_time / bin_width_s))) if avg_time > 0 else 1
        n_bins = min(n_bins, len(total_counts))
        return float(np.nanmean(total_counts[-n_bins:]))
