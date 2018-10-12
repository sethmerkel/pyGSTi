""" Idle Tomography reporting and plotting functions """
from __future__ import division, print_function, absolute_import, unicode_literals

import time as _time
import numpy as _np
import itertools as _itertools
import collections as _collections

from ... import _version
from ...baseobjs import VerbosityPrinter as _VerbosityPrinter
from ...report import workspace as _ws
from ...report import workspaceplots as _wp
from ...report import table as _reporttable
from ...report import figure as _reportfigure
from ...report import merge_helpers as _merge
from ...tools  import timed_block as _timed_block
from . import pauliobjs as _pobjs

import plotly.graph_objs as go


#HERE - need to create this table of intrinsic values, then
# - map each intrinsic value to a set of observable rates via jacobians,
#   maybe as a list of (typ, fidpair, obs/outcome, jac_element) tuples?
# - create plots for a/each observable rate, i.e., for any such tuple above,
#   and maybe allow multiple idtresults as input...
# - create another workspace table that displays all the above such plots
#   that affect a given intrinsic rate.
# - report/tab will show intrinsic-rates table and a switchboard that allows the
#   user to select a given intrinsic rate and displays the corresponding table of
#   observable rate plots.


class IdleTomographyObservedRatesTable(_ws.WorkspaceTable):
    """ 
    TODO: docstring
    """
    def __init__(self, ws, idtresult, typ, errorOp):
        """
        TODO: docstring
        idtresult may be a list or results too? titles?

        Returns
        -------
        ReportTable
        """
        super(IdleTomographyObservedRatesTable,self).__init__(
            ws, self._create, idtresult, typ, errorOp)

    def _create(self, idtresult, typ, errorOp):
        colHeadings = ['Jacobian El', 'Observable Rate']

        if not isinstance(errorOp, _pobjs.NQPauliOp):
            errorOp = _pobjs.NQPauliOp(errorOp) # try to init w/whatever we've been given

        intrinsicIndx = idtresult.error_list.index(errorOp)

        if typ in ('stochastic','affine') and \
                'stochastic/affine' in idtresult.pauli_fidpairs: 
            typ = 'stochastic/affine' # for intrinsic stochastic and affine types
            if typ == "affine":  # affine columns follow all stochastic columns in jacobian
                intrinsicIndx += len(idtresult.error_list)

        #get all the observable rates that contribute to the intrinsic
        # rate specified by `typ` and `errorOp`
        obs_rate_specs = []
        #print("DB: err list = ",idtresult.error_list, " LEN=",len(idtresult.error_list))
        #print("DB: Intrinsic index = ",intrinsicIndx)
        for fidpair,dict_of_infos in zip(idtresult.pauli_fidpairs[typ],
                                         idtresult.observed_rate_infos[typ]):
            for obsORoutcome,info_dict in dict_of_infos.items():
                jac_element = info_dict['jacobian row'][intrinsicIndx]
                if abs(jac_element) > 0:
                    #print("DB: found in Jrow=",info_dict['jacobian row'], " LEN=",len(info_dict['jacobian row']))
                    #print("   (fidpair = ",fidpair[0],fidpair[1]," o=",obsORoutcome)
                    obs_rate_specs.append( (fidpair, obsORoutcome, jac_element) )

        #TODO: sort obs_rate_specs in some sensible way
        
        table = _reporttable.ReportTable(colHeadings, (None,)*len(colHeadings))
        for fidpair, obsOrOutcome, jac_element in obs_rate_specs:
            fig = IdleTomographyObservedRatePlot(self.ws, idtresult, typ, 
                                                 fidpair, obsOrOutcome, title="auto")
            row_data = [str(jac_element), fig]
            row_formatters = [None, 'Figure']
            table.addrow(row_data, row_formatters)

        table.finish()
        return table
        



class IdleTomographyObservedRatePlot(_ws.WorkspacePlot):
    """ TODO """
    def __init__(self, ws, idtresult, typ, fidpair, obsORoutcome, title="auto",
                 true_rate=None, scale=1.0):
        super(IdleTomographyObservedRatePlot,self).__init__(
            ws, self._create, idtresult, typ, fidpair, obsORoutcome,
                 title, true_rate, scale)
        
    def _create(self, idtresult, typ, fidpair, obsORoutcome,
                 title, true_rate, scale):

        if title == "auto":
            title = typ + " fidpair=%s,%s" % (fidpair[0],fidpair[1])
            if typ == "hamiltonian":
                title += " observable="+str(obsORoutcome)
            else:
                title += " outcome="+str(obsORoutcome)   

        xlabel = "Length"
        if typ == "hamiltonian": 
            ylabel =  "Expectation value"
        else:
            ylabel = "Outcome probability"
    
        maxLens = idtresult.max_lengths
        ifidpair = idtresult.pauli_fidpairs[typ].index(fidpair)
        info_dict = idtresult.observed_rate_infos[typ][ifidpair][obsORoutcome]
        obs_rate = info_dict['rate']
        data_pts = info_dict['data']
        weights = info_dict['weights']
        fitCoeffs = info_dict['fitCoeffs']
        fitOrder = info_dict['fitOrder']
    
        traces = []
        traces.append( go.Scatter(
            x=maxLens,
            y=data_pts,
            mode="markers",
            marker=dict(
                color = 'black',
                size=10),
            name='observed data' ))
    
        x = _np.linspace(maxLens[0],maxLens[-1],50)
        if len(fitCoeffs) == 2: # 1st order fit
            assert(_np.isclose(fitCoeffs[0], obs_rate))
            fit = fitCoeffs[0]*x + fitCoeffs[1]
            fit_line = None
        elif len(fitCoeffs) == 3:
            fit = fitCoeffs[0]*x**2 + fitCoeffs[1]*x + fitCoeffs[2]
            #OLD: assert(_np.isclose(fitCoeffs[1], obs_rate))
            #OLD: fit_line = fitCoeffs[1]*x + (fitCoeffs[0]*x[0]**2 + fitCoeffs[2])
            det = fitCoeffs[1]**2 - 4*fitCoeffs[2]*fitCoeffs[0]
            slope = -_np.sign(fitCoeffs[0])*_np.sqrt(det) if det >= 0 else fitCoeffs[1]
            fit_line = slope*x + (fit[0]-slope*x[0])
            assert(_np.isclose(slope, obs_rate))
        else:
            #print("DB: ",fitCoeffs)
            raise NotImplementedError("Only up to order 2 fits!")
    
        traces.append( go.Scatter(
            x=x,
            y=fit,
            mode="lines", #dashed? "markers"? 
            marker=dict(
                color = 'rgba(0,0,255,0.8)',
                line = dict(
                    width = 2,
                    )),
            name='o(%d) fit (slope=%.2g)' % (fitOrder,obs_rate)))
    
        if fit_line is not None:
            traces.append( go.Scatter(
                x=x,
                y=fit_line,
                mode="lines",
                marker=dict(
                    color = 'rgba(0,0,200,0.8)',
                    line = dict(
                        width = 1,
                        )),
                name='o(%d) fit slope' % fitOrder))
    
        if true_rate:
            traces.append( go.Scatter(
                x=x,
                y=(fit[0]-true_rate*x[0])+true_rate*x,
                mode="lines", #dashed? "markers"? 
                marker=dict(
                    color = 'rgba(0,0,255,0.8)', # black?
                    line = dict(
                        width = 2,
                        )),
                name='true rate = %g' % true_rate))
    
        layout = go.Layout(
            width=700*scale,
            height=400*scale,
            title=title,
            font=dict(size=10),
            xaxis=dict(
                title=xlabel,
                ),
            yaxis=dict(
                    title=ylabel,
                ),
            )
    
        pythonVal = {} # TODO
        return _reportfigure.ReportFigure(
            go.Figure(data=traces, layout=layout),
            None, pythonVal)

    

class IdleTomographyIntrinsicErrorsTable(_ws.WorkspaceTable):
    """ 
    TODO: docstring
    """

    def __init__(self, ws, idtresults, 
                 display=("H","S","A"), display_as="boxes"):
        """
        TODO: docstring
        idtresults may be a list or results too? titles?

        Returns
        -------
        ReportTable
        """
        super(IdleTomographyIntrinsicErrorsTable,self).__init__(
            ws, self._create, idtresults, display, display_as)

    def _create(self, idtresults, display, display_as):
        colHeadings = ['Qubits']

        for disp in display:
            if disp == "H":
                colHeadings.append('Hamiltonian')
            elif disp == "S":
                colHeadings.append('Stochastic')
            elif disp == "A":
                colHeadings.append('Affine')
            else: raise ValueError("Invalid display element: %s" % disp)

        assert(display_as == "boxes" or display_as == "numbers")
        table = _reporttable.ReportTable(colHeadings, (None,)*len(colHeadings))

        #Process list of intrinsic rates, binning into rates for different sets of qubits
        def process_rates(typ):
            rates = _collections.defaultdict(dict)
            for err, value in zip(idtresults.error_list,
                                  idtresults.intrinsic_rates[typ]):
                qubits = [i for i,P in enumerate(err.rep) if P != 'I'] # (in sorted order)
                op    = _pobjs.NQPauliOp(''.join([P for P in err.rep if P != 'I']))
                rates[tuple(qubits)][op] = value
            return rates

        M = 0; all_keys = set()
        ham_rates = sto_rates = aff_rates = {} # defaults
        if 'H' in display:
            ham_rates = process_rates('hamiltonian')
            M = max(M,max(_np.abs(idtresults.intrinsic_rates['hamiltonian'])))
            all_keys.update(ham_rates.keys())
        if 'S' in display:
            sto_rates = process_rates('stochastic')
            M = max(M,max(_np.abs(idtresults.intrinsic_rates['stochastic'])))
            all_keys.update(sto_rates.keys())
        if 'A' in display:
            aff_rates = process_rates('affine')
            M = max(M,max(_np.abs(idtresults.intrinsic_rates['affine'])))
            all_keys.update(aff_rates.keys())

        #min/max
        m = -M


        def get_plot_info(qubits, rate_dict):
            wt = len(qubits) # the weight of the errors
            basisLblLookup = { _pobjs.NQPauliOp(''.join(tup)):i for i,tup in 
                               enumerate(_itertools.product(["X","Y","Z"],repeat=wt)) }
            #print("DB: ",list(basisLblLookup.keys()))
            #print("DB: ",list(rate_dict.keys()))
            values = _np.zeros(len(basisLblLookup),'d')
            for op,val in rate_dict.items():
                values[basisLblLookup[op]] = val
            if wt == 2:
                xlabels = ["X","Y","Z"]
                ylabels = ["X","Y","Z"]
                values = values.reshape((3,3))
            else:
                xlabels = list(_itertools.product(["X","Y","Z"],repeat=wt))
                ylabels = [""]
                values = values.reshape((1,len(values)))
            return values, xlabels, ylabels
                                    
        sorted_keys = sorted(list(all_keys), key=lambda x: (len(x),)+x)

        #Create rows with plots
        for ky in sorted_keys:
            row_data = [str(ky)]
            row_formatters = [None]

            for disp in display:
                if disp == "H" and ky in ham_rates:
                    values, xlabels, ylabels = get_plot_info(ky,ham_rates[ky])
                    if display_as == "boxes":
                        fig = _wp.MatrixPlot(
                            self.ws, values, m, M, xlabels, ylabels, 
                            boxLabels=True, prec="compacthp")
                        row_data.append(fig)
                        row_formatters.append('Figure')
                    else:
                        row_data.append(values)
                        row_formatters.append('Brackets')

                if disp == "S" and ky in sto_rates:
                    values, xlabels, ylabels = get_plot_info(ky,sto_rates[ky])
                    if display_as == "boxes":
                        fig = _wp.MatrixPlot(
                            self.ws, values, m, M, xlabels, ylabels, 
                            boxLabels=True, prec="compacthp")
                        row_data.append(fig)
                        row_formatters.append('Figure')
                    else:
                        row_data.append(values)
                        row_formatters.append('Brackets')

                if disp == "A" and ky in aff_rates:
                    values, xlabels, ylabels = get_plot_info(ky,aff_rates[ky])
                    if display_as == "boxes":
                        fig = _wp.MatrixPlot(
                            self.ws, values, m, M, xlabels, ylabels, 
                            boxLabels=True, prec="compacthp")
                        row_data.append(fig)
                        row_formatters.append('Figure')
                    else:
                        row_data.append(values)
                        row_formatters.append('Brackets')

            table.addrow(row_data, row_formatters)

        table.finish()
        return table

#Note: SAME function as in report/factory.py (copied)
def _add_new_labels(running_lbls, current_lbls):
    """
    Simple routine to add current-labels to a list of
    running-labels without introducing duplicates and
    preserving order as best we can.
    """
    if running_lbls is None:
        return current_lbls[:] #copy!
    elif running_lbls != current_lbls:
        for lbl in current_lbls:
            if lbl not in running_lbls:
                running_lbls.append(lbl)
    return running_lbls

def _create_switchboard(ws, results_dict, printer, fmt):
    """
    Creates the switchboard used by the idle tomography report
    """

    if isinstance(results_dict, _collections.OrderedDict):
        dataset_labels = list(results_dict.keys())
    else:
        dataset_labels = sorted(list(results_dict.keys()))

    errortype_labels = None
    errorop_labels = None
    for results in results_dict.values():
        errorop_labels = _add_new_labels(errorop_labels, [str(e).strip() for e in results.error_list])
        errortype_labels   = _add_new_labels(errortype_labels, list(results.intrinsic_rates.keys()))
    errortype_labels = list(sorted(errortype_labels))
        
    multidataset = bool(len(dataset_labels) > 1)

    switchBd = ws.Switchboard(
        ["Dataset","ErrorType","ErrorOp"],
        [dataset_labels,errortype_labels,errorop_labels],
        ["dropdown","dropdown","dropdown"], [0,0,0],
        show=[multidataset,False,False] # only show dataset dropdown (for sidebar)
    )

    switchBd.add("results",(0,))
    switchBd.add("errortype",(1,))
    switchBd.add("errorop",(2,))

    for d,dslbl in enumerate(dataset_labels):
        switchBd.results[d] = results_dict[dslbl]

    for i,etyp in enumerate(errortype_labels):
        switchBd.errortype[i] = etyp

    for i,eop in enumerate(errorop_labels):
        switchBd.errorop[i] = eop
        
    return switchBd, dataset_labels



def create_idletomography_report(results, filename, title="auto",
                                 ws=None, auto_open=False, link_to=None,
                                 brevity=0, advancedOptions=None, verbosity=1):
    """
    TODO: docstring 

    Returns
    -------
    Workspace
        The workspace object used to create the report
    """
    tStart = _time.time()
    printer = _VerbosityPrinter.build_printer(verbosity) #, comm=comm)

    if advancedOptions is None: advancedOptions = {}
    precision = advancedOptions.get('precision', None)
    cachefile = advancedOptions.get('cachefile',None)
    connected = advancedOptions.get('connected',False)
    resizable = advancedOptions.get('resizable',True)
    autosize = advancedOptions.get('autosize','initial')

    if filename and filename.endswith(".pdf"):
        fmt = "latex"
    else:
        fmt = "html"
        
    printer.log('*** Creating workspace ***')
    if ws is None: ws = _ws.Workspace(cachefile)

    if title is None or title == "auto":
        if filename is not None:
            autoname = _autotitle.generate_name()
            title = "Idle Tomography Report for " + autoname
            _warnings.warn( ("You should really specify `title=` when generating reports,"
                             " as this makes it much easier to identify them later on.  "
                             "Since you didn't, pyGSTi has generated a random one"
                             " for you: '{}'.").format(autoname))
        else:
            title = "N/A" # No title - but it doesn't matter since filename is None

    results_dict = results if isinstance(results, dict) else {"unique": results}

    renderMath = True

    qtys = {} # stores strings to be inserted into report template
    def addqty(b, name, fn, *args, **kwargs):
        """Adds an item to the qtys dict within a timed block"""
        if b is None or brevity < b:
            with _timed_block(name, formatStr='{:45}', printer=printer, verbosity=2):
                qtys[name] = fn(*args, **kwargs)

    qtys['title'] = title
    qtys['date'] = _time.strftime("%B %d, %Y")

    pdfInfo = [('Author','pyGSTi'), ('Title', title),
               ('Keywords', 'GST'), ('pyGSTi Version',_version.__version__)]
    qtys['pdfinfo'] = _merge.to_pdfinfo(pdfInfo)

    # Generate Switchboard
    printer.log("*** Generating switchboard ***")

    #Create master switchboard
    switchBd, dataset_labels = \
            _create_switchboard(ws, results_dict, printer, fmt)
    if fmt == "latex" and (len(dataset_labels) > 1):
        raise ValueError("PDF reports can only show a *single* dataset," +
                         " estimate, and gauge optimization.")

    # Generate Tables
    printer.log("*** Generating tables ***")

    multidataset = bool(len(dataset_labels) > 1)
    intErrView = [False,True,True]

    if fmt == "html":
        qtys['topSwitchboard'] = switchBd
        qtys['intrinsicErrSwitchboard'] = switchBd.view(intErrView,"v1")

    results = switchBd.results
    errortype = switchBd.errortype
    errorop = switchBd.errorop
    A = None # no brevity restriction: always display; for "Summary"- & "Help"-tab figs

    #Brevity key:
    # TODO - everything is always displayed for now

    addqty(A,'intrinsicErrorsTable', ws.IdleTomographyIntrinsicErrorsTable, results)
    addqty(A,'observedRatesTable', ws.IdleTomographyObservedRatesTable, results, errortype, errorop)


    # Generate plots
    printer.log("*** Generating plots ***")

    toggles = {}
    toggles['CompareDatasets'] = False # not comparable by default
    if multidataset:
        #check if data sets are comparable (if they have the same sequences)
        comparable = True
        gstrCmpList = list(results_dict[ dataset_labels[0] ].dataset.keys()) #maybe use gatestring_lists['final']??
        for dslbl in dataset_labels:
            if list(results_dict[dslbl].dataset.keys()) != gstrCmpList:
                _warnings.warn("Not all data sets are comparable - no comparisions will be made.")
                comparable=False; break

        if comparable:
            #initialize a new "dataset comparison switchboard"
            dscmp_switchBd = ws.Switchboard(
                ["Dataset1","Dataset2"],
                [dataset_labels, dataset_labels],
                ["buttons","buttons"], [0,1]
            )
            dscmp_switchBd.add("dscmp",(0,1))
            dscmp_switchBd.add("dscmp_gss",(0,))
            dscmp_switchBd.add("refds",(0,))

            for d1, dslbl1 in enumerate(dataset_labels):
                dscmp_switchBd.dscmp_gss[d1] = results_dict[dslbl1].gatestring_structs['final']
                dscmp_switchBd.refds[d1] = results_dict[dslbl1].dataset #only used for #of spam labels below

            dsComp = dict()
            all_dsComps = dict()
            indices = []
            for i in range(len(dataset_labels)):
                for j in range(len(dataset_labels)):
                    indices.append((i, j))

            #REMOVE (for using comm)
            #if comm is not None:
            #    _, indexDict, _ = _distribute_indices(indices, comm)
            #    rank = comm.Get_rank()
            #    for k, v in indexDict.items():
            #        if v == rank:
            #            d1, d2 = k
            #            dslbl1 = dataset_labels[d1]
            #            dslbl2 = dataset_labels[d2]
            #
            #            ds1 = results_dict[dslbl1].dataset
            #            ds2 = results_dict[dslbl2].dataset
            #            dsComp[(d1, d2)] = _DataComparator(
            #                [ds1, ds2], DS_names=[dslbl1, dslbl2])
            #    dicts = comm.gather(dsComp, root=0)
            #    if rank == 0:
            #        for d in dicts:
            #            for k, v in d.items():
            #                d1, d2 = k
            #                dscmp_switchBd.dscmp[d1, d2] = v
            #                all_dsComps[(d1,d2)] = v
            #else:
            for d1, d2 in indices:
                dslbl1 = dataset_labels[d1]
                dslbl2 = dataset_labels[d2]
                ds1 = results_dict[dslbl1].dataset
                ds2 = results_dict[dslbl2].dataset
                all_dsComps[(d1,d2)] =  _DataComparator([ds1, ds2], DS_names=[dslbl1,dslbl2])
                dscmp_switchBd.dscmp[d1, d2] = all_dsComps[(d1,d2)]

            qtys['dscmpSwitchboard'] = dscmp_switchBd
            addqty(4,'dsComparisonSummary', ws.DatasetComparisonSummaryPlot, dataset_labels, all_dsComps)
            #addqty('dsComparisonHistogram', ws.DatasetComparisonHistogramPlot, dscmp_switchBd.dscmp, display='pvalue')
            addqty(4,'dsComparisonHistogram', ws.ColorBoxPlot,
                   'dscmp', dscmp_switchBd.dscmp_gss, dscmp_switchBd.refds, None,
                   dscomparator=dscmp_switchBd.dscmp, typ="histogram", comm=comm)
            addqty(1,'dsComparisonBoxPlot', ws.ColorBoxPlot, 'dscmp', dscmp_switchBd.dscmp_gss,
                   dscmp_switchBd.refds, None, dscomparator=dscmp_switchBd.dscmp, comm=comm)
            toggles['CompareDatasets'] = True
        else:
            toggles['CompareDatasets'] = False # not comparable!
    else:
        toggles['CompareDatasets'] = False


    if filename is not None:
        if True: # comm is None or comm.Get_rank() == 0:
            # 3) populate template file => report file
            printer.log("*** Merging into template file ***")

            if fmt == "html":
                templateDir = "idletomography_html_report"
                _merge.merge_html_template_dir(
                    qtys, templateDir, filename, auto_open, precision, link_to,
                    connected=connected, toggles=toggles, renderMath=renderMath,
                    resizable=resizable, autosize=autosize, verbosity=printer)

            elif fmt == "latex":
                raise NotImplementedError("No PDF version of this report is available yet.")
                templateFile = "idletomography_pdf_report.tex"
                base = _os.path.splitext(filename)[0] # no extension
                _merge.merge_latex_template(qtys, templateFile, base+".tex", toggles,
                                            precision, printer)

                # compile report latex file into PDF
                cmd = _ws.WorkspaceOutput.default_render_options.get('latex_cmd',None)
                flags = _ws.WorkspaceOutput.default_render_options.get('latex_flags',[])
                assert(cmd), "Cannot render PDF documents: no `latex_cmd` render option."
                printer.log("Latex file(s) successfully generated.  Attempting to compile with %s..." % cmd)
                _merge.compile_latex_report(base, [cmd] + flags, printer, auto_open)
            else:
                raise ValueError("Unrecognized format: %s" % fmt)
    else:
        printer.log("*** NOT Merging into template file (filename is None) ***")
    printer.log("*** Report Generation Complete!  Total time %gs ***" % (_time.time()-tStart))

    return ws
