# bbx python package:

import sys
import os

import gzip
import numpy as np
import struct

SUPPORTED_FILE_SIGNATURES = ['\x02BX', 'ABX']
SUPPORTED_ENCODING_SCHEMES = ['raw256']
SUPPORTED_HDR_TYPES = ['LoFASM-filterbank']
REQUIRED_HDR_COMMENT_FIELDS = {
    'LoFASM-filterbank': ['hdr_type', 'hdr_version', 'station', 'channel',
                       'dim1_start', 'dim1_span', 'dim2_start', 'dim2_span',
                       'data_type']
}

class LofasmFile(object):
    """Class to represent .bbx-type data files for LoFASM.

    Currently, the only data format supported is 'LoFASM-filterbank'.
    """
    def __init__(self, lofasm_file, verbose=False, mode='read', gz=None):
        self.debug = True if verbose else False
        self.header = {}
        self.iscplx = None
        self.fpath = lofasm_file
        self.fname = os.path.basename(lofasm_file)

        # validate file open mode
        if mode.lower() not in ('read', 'write'):
            raise ValueError("Unrecognized file mode: {}".format(mode.lower()))
        else:
            mode = mode.lower()
            if mode == 'read':
                self._fmode = 'rb'
            elif mode == 'write':
                self._fmode = 'wb'
            self.mode = mode

        # check existence of file
        if not os.path.exists(lofasm_file):
            if mode == 'read':
                raise RuntimeError("File does not exist: {}".format(lofasm_file))
        elif mode == 'read':
            assert(os.path.getsize(lofasm_file) > 0), "File is empty"


        if mode in ['read'] and gz == None:
            try:
                with gzip.open(self.fpath, self._fmode) as f:
                    gz = True if f.readline() else False
            except IOError as e:
                if e.message == 'Not a gzipped file':
                    gz = False
                else:
                    raise IOError, e.message
        elif mode == 'write':
            gz = gz if gz else False

        self.gz = gz
        self._fp = gzip.open(self.fpath, self._fmode) if gz else open(self.fpath, self._fmode)

        if mode in ['read']:
            self._load_header()
        elif mode == 'write':
            print "prepping file"
            self._prep_new()

        # private copy of certain methods
        self._set = self.set

    # #############################
    # Top level interface methods #
    # #############################
    def add_data(self, data):
        """
        add BBX data to memory to be written to file.

        Write 1d or 2d data to memory to be written to disk.
        If invoked with a new file then the dimension fields in the
        metadata will be set.

        Parameters
        ----------
        data : numpy.ndarray
            Data array to be added to memory
            `data.ndim` must be either 1 or 2.
            The data type of the elements in the stored array will be
            inferred from `data`
            Supported data types are np.complex128 and np.float64.

        Raises
        ------
        AssertionError
            If file is not opened in write mode.

        NotImplementedError
            If the dimensions of `data` are not supported.

        ValueError
            If either the number of channels in `data` or the data type doesn't match the pre-existing data, if there is
            any.
        """
        assert(self.mode == 'write'), "File not open for writing."

        if data.ndim == 2:
            tbins, fbins = np.shape(data)
            data = data.flatten()
        elif data.ndim == 1:
            data = data.flatten()
            fbins = len(data)
            tbins = 1
        else:
            raise NotImplementedError, "Currently only up to 2d data is supported."

        if self._new_file:
            self._set('dim1_len', str(tbins))
            self._set('dim2_len', str(fbins))
            self._set('complex', '2' if np.iscomplexobj(data) else '1')
            N = tbins * fbins
            self.data = np.zeros(N, dtype=np.complex128 if np.iscomplexobj(data) else np.float64)
            self.data[:N] = data

        else:
            old_iscplx = True if self.header['metadata'][2] == '2' else False
            new_iscplx = np.iscomplexobj(data)

            if old_iscplx != new_iscplx:
                raise ValueError, "new data must match existing data realness"

            if str(fbins) != self.freqbins:
                raise ValueError, "new data must have same number of frequency bins as existing data"


            new_bins = fbins * tbins
            N = len(self.data) + int(new_bins)
            newdata = np.zeros(N, dtype=self.data.dtype)
            newdata[:-N] = self.data
            newdata[-N:] = data
            self.data = newdata

    def close(self):
        """
        close file object
        """
        self._fp.close()

    def read_data(self, num_time_bin=None):
        """Parse data block in LoFASM filterbank file and load into memory as `self.data`.

        The resulting data array in self.data is stored as a 2d array with dim1 as the horizontal axis and
        dim2 as the vertical axis.

        If reading a typical LoFASM-filterbank file then the x-axis will represent the time bins and the y-axis will
        represent the frequency bins.

        Parameters
        ----------
        num_time_bin : int
            The number of time bins to read. If not provided, then attempt to read the entire file.
            If `num_time_bin` is larger than the number of time bins in the file then read the entire file.
            A value of 0 will result in nothing being read.
        Raises
        ------
        AssertionError
            If file is not open for reading
        """


        assert(self.mode == 'read'), "File not open for reading."

        if num_time_bin:
            if num_time_bin > self.timebins:
                num_time_bin = self.timebins
            elif num_time_bin < 0:
                return
        else:
            num_time_bin = self.timebins

        if not self.iscplx:
            nbytes = self.freqbins * self.nbits / 8
            self.data = np.zeros((int(self.freqbins), int(num_time_bin)), dtype=np.float64)
            self.dtype = self.data.dtype
            for col in range(num_time_bin):
                spec = struct.unpack('{}d'.format(self.freqbins),
                                     self._fp.read(nbytes))
                self.data[:,col] = spec
        else:
            nbytes = 2 * self.freqbins * self.nbits / 8
            self.data = np.zeros((int(self.freqbins), int(num_time_bin)), dtype=np.complex64)
            self.dtype = self.data.dtype
            for col in range(num_time_bin):
                spec_cmplx = struct.unpack('{}d'.format(2*self.freqbins),
                                           self._fp.read(nbytes))
                i=0
                for row in range(len(spec_cmplx)/2):
                    self.data[row, col] = np.complex64(complex(spec_cmplx[i], spec_cmplx[i+1]))
                    i += 2

    def set(self, key, val):
        """Set header or metadata fields

        Set or create header comment fields. If the field `key` exists then its value will be overwritten.
        If the field does not exist, then it will be created as a new comment field.

        If `key` exists as part of the metadata field, then the value will be overwritten.

        Parameters
        ----------
        key : str
            Header field name as a string.
        val : str, int, float
            Value that header field will be set to
        """
        if key in self.metadata.keys():
            self.metadata[key] = val
        elif key in self.header.keys():
            self.header[key] = val
        else:
            self._debug("Creating header field {}: {}".format(key, val))
            self.header[key] = val

    def write(self):
        """
        Write current data contents to disk.

        If at the beginning of the file write the BBX header first, then the data.
        """

        assert (self.mode == 'write'), "File not open for writing."

        missing_keys = []
        for key in REQUIRED_HDR_COMMENT_FIELDS['LoFASM-filterbank']:
            if self.header[key] == None:
                missing_keys.append(key)
        if missing_keys:
            raise RuntimeError, "the header is missing some required fields: {}".format(', '.join(missing_keys))

        if self._fp.tell() == 0:
            self._write_header()

        N = len(self.data)
        realfmt = '{}d'.format(N)
        cplxfmt = '{}d'.format(2*N)

        if np.iscomplexobj(self.data):
            cplxdata = np.zeros(2*N, dtype=self.data.dtype)
            i = 0
            for k in range(N):
                cplxdata[i] = self.data[k].real
                cplxdata[i+1] = self.data[k].imag
                i += 2
            self._fp.write(struct.pack(cplxfmt, *cplxdata))
        else:
            self._fp.write(struct.pack(realfmt, *self.data))

    ###################
    # Private methods #
    ###################
    def _debug(self, msg):
        if self.debug:
            print msg
            sys.stdout.flush()

    def _load_header(self):
        try:
            fsig = self._fp.readline().strip()
            if fsig.startswith('%'):
                fsig = fsig.strip('%')
            elif self.gz:
                raise IOError, "Unable to parse file. Unrecognizable file signature. Are you sure compression should be turned on?"
            else:
                raise IOError, "Unable to parse file. Unrecognizable file signature."
        except IOError as e:
            if self.gz and e.strerror == 'Not a gzipped file':
                raise IOError, "Compression parameter is True but input file is not a gzipped file"
            else:
                raise IOError, e.message

        if fsig not in SUPPORTED_FILE_SIGNATURES:
            raise NotImplementedError("{} is not a supported LoFASM file signature".format(fsig))

        # populate header dictionary with header comment fields
        line = self._fp.readline().strip()
        while line.startswith('%'):
            contents = line.strip('%').split(":")
            key = contents[0]
            val = ':'.join(contents[1:])
            self.header[key] = val.strip()
            line = self._fp.readline().strip()

        # check for hdr_type field first. This is how we determine what fields are required
        if 'hdr_type' not in self.header.keys():
            raise RuntimeError("Missing Required comment field: hdr_type")

        missing_comment_fields = []
        for key in REQUIRED_HDR_COMMENT_FIELDS[self.header['hdr_type']]:
            if key not in self.header.keys():
                missing_comment_fields.append(key)
        if missing_comment_fields:
            raise RuntimeError("Missing required comment fields for {} header type: {}".format(
                self.header['hdr_type'], ', '.join(missing_comment_fields)))

        # parse metadata line in file header
        contents = line.split()
        if len(contents) != 5:  # FixMe: this is only stable for LoFASM-filterbank files
            raise RuntimeError("Unable to parse metadata line: {}".format(line))

        metadata = {}
        metadata['dim1_len'] = int(contents[0])
        metadata['dim2_len'] = int(contents[1])

        # determine whether data is real or complex
        #  real (auto correlation) data: 1
        #  complex (cross correlation) data: 2
        #  other: unknown
        if int(contents[2]) == 1:
            metadata['complex'] = False
        elif int(contents[2]) == 2:
            metadata['complex'] = True
        else:
            raise ValueError("Cannot determine whether data is complex or real.")

        metadata['nbits'] = int(contents[3])

        if contents[4] in SUPPORTED_ENCODING_SCHEMES:
            metadata['encoding'] = contents[4]
        else:
            raise RuntimeError("Unsupported encoding scheme: {}".format(contents[4]))

        self.header['metadata'] = metadata

        if self.debug:
            for k in self.header.keys():
                if k == 'metadata':
                    x = str(metadata)
                else:
                    x = self.header[k]
                self._debug("Loaded {}: {}".format(k, x))

        self.iscplx = self.complex

    def _prep_new(self):
        """
        prepare object to begin writing a new bbx file.
        :return:
        """
        metadata = {
            'dim1_len': None,
            'dim2_len': None,
            'complex': None,
            'nbits': 64,
            'encoding': 'raw256'
        }
        if self.iscplx:
            metadata['complex'] = '2'
        elif self.iscplx is False:
            metadata['complex'] = '1'

        self.header = {'hdr_type': 'LoFASM-filterbank',
               'hdr_version': '0000803F',
               'station': None,
               'channel': None,
               'dim1_start': None,
               'dim1_label': 'time (s)',
               'dim1_span': None,
               'dim2_label': 'frequency (Hz)',
               'dim2_start': None,
               'dim2_span': None,
               'data_type': 'real64',
               'metadata': metadata}

        self._new_file = True

    def _validate_header(self):
        """
        return True if all the required fields in self.header are set, else False
        :return: bool
            True if header is ready to be written, False otherwise
        """

        for key in REQUIRED_HDR_COMMENT_FIELDS['LoFASM-filterbank']:
            if self.header[key] == None:
                break
        else:
            return True

        return False

    def _write_header(self):
        """
        write header to file if self.header is sufficiently populated
        """

        assert (self._validate_header()), "Header is not sufficiently populated"

        # start file with BBX file signature
        self._fp.write("%\x02BX\n")

        keystowrite = self.header.keys()
        self._fp.write("%hdr_type: {}\n".format(self.header['hdr_type']))
        keystowrite.remove('hdr_type')
        keystowrite.remove('metadata')

        # write all remaining comment fields
        for key in keystowrite:
            self._fp.write("%{}: {}\n".format(key, self.header[key]))

        # end header with metadata line
        meta = [str(x) for x in [self.dim1_len, self.dim2_len, self.complex, self.nbits, self.encoding]]
        self._fp.write("{}\n".format(' '.join(meta)))

    ###################
    # Magic methods #
    ###################
    def __getattr__(self, key):
        """
        Check self.header and internal scope (self.__dict__) dictionaries when
        fetching an attribute.
        :param key: str
            name of attribute
        :return:
            value of matched attribute
        :raises:
            AttributeError if attribute is not found.
        """
        if key in self.header.keys():
            val = self.header[key]
        elif key in self.metadata.keys():
            val = self.metadata[key]
        elif key == 'timebins':
            val = self.metadata['dim1_len']
        elif key == 'freqbins':
            val = self.metadata['dim2_len']
        elif key in self.__dict__.keys():
            val = self.__dict__[key]
        else:
            raise AttributeError("LoFASM File class has no attribute {}".format(key))

        return val