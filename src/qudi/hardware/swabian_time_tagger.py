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

    def get_counts(self):
        counts = self.counter.getDataNormalized()
        # counts_spad_1 = counts[0]
        # counts_spad_2 = counts[1]
        total_counts = counts[0] + counts[1]
        # print(np.nanmean(total_counts))
        # print("getting counts from time tagger")
        return np.nanmean(total_counts)
