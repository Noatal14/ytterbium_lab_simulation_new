import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit

__all__ = ["make_graph"]


def _linear_model(x, a, b):
    return a * x + b


def _polynomial_model(x, *coeffs):
    return np.polyval(coeffs, x)


def _power_model(x, a, b):
    return a * np.power(x, b)


def _power_offset_model(x, a, b, c):
    return a * np.power(x, b) + c


def _shifted_power_model(x, a, b, x0):
    return a * np.power(x - x0, b)


def _safe_curve_fit(model, x, y, p0=None, sigma=None):
    # Protect against zero sigma values
    if sigma is not None:
        sigma = np.asarray(sigma)
        if sigma.shape == ():
            if sigma == 0:
                sigma = None
        else:
            # replace zeros with small epsilon to avoid division issues
            sigma = np.where(sigma == 0, np.finfo(float).eps, sigma)

    with np.errstate(all='ignore'):
        if sigma is None:
            popt, _ = curve_fit(model, x, y, p0=p0, maxfev=10000)
        else:
            popt, _ = curve_fit(model, x, y, p0=p0, sigma=sigma, absolute_sigma=True, maxfev=10000)
    return popt


def _resolve_fit_spec(fit):
    if fit is None or fit is False:
        return None

    if isinstance(fit, str):
        return {"type": fit}

    if isinstance(fit, (tuple, list)):
        if len(fit) == 0:
            raise ValueError("Fit tuple/list must contain at least a type string.")
        fit_type = fit[0]
        return {"type": fit_type, "args": tuple(fit[1:])}

    if isinstance(fit, dict):
        return fit.copy()

    raise ValueError("Unsupported fit specification type. Use str, tuple/list, dict, or None.")


def _generate_fit(x, y, fit, yerr=None):
    fit_spec = _resolve_fit_spec(fit)
    if fit_spec is None:
        return None

    fit_type = fit_spec.get("type")
    args = fit_spec.get("args", ())

    if fit_type == "linear":
        params = _safe_curve_fit(_linear_model, x, y, p0=[1.0, 0.0], sigma=yerr)
        return {
            "type": "linear",
            "params": params,
            "model": _linear_model,
            "label": f"linear fit: y = {params[0]:.3g} x + {params[1]:.3g}",
        }

    if fit_type == "quadratic":
        if yerr is not None:
            w = 1.0 / np.asarray(yerr)
            coeffs = np.polyfit(x, y, 2, w=w)
        else:
            coeffs = np.polyfit(x, y, 2)
        return {
            "type": "quadratic",
            "params": coeffs,
            "model": lambda x_vals, *p: _polynomial_model(x_vals, *p),
            "label": f"quadratic fit: y = {coeffs[0]:.3g} x^2 + {coeffs[1]:.3g} x + {coeffs[2]:.3g}",
        }

    if fit_type == "cubic":
        if yerr is not None:
            w = 1.0 / np.asarray(yerr)
            coeffs = np.polyfit(x, y, 3, w=w)
        else:
            coeffs = np.polyfit(x, y, 3)
        return {
            "type": "cubic",
            "params": coeffs,
            "model": lambda x_vals, *p: _polynomial_model(x_vals, *p),
            "label": f"cubic fit",
        }

    if fit_type == "poly":
        if len(args) != 1 or not isinstance(args[0], int):
            raise ValueError("""poly fit requires a single integer degree, e.g. ('poly', 3)""")
        degree = args[0]
        if yerr is not None:
            w = 1.0 / np.asarray(yerr)
            coeffs = np.polyfit(x, y, degree, w=w)
        else:
            coeffs = np.polyfit(x, y, degree)
        return {
            "type": "poly",
            "degree": degree,
            "params": coeffs,
            "model": lambda x_vals, *p: _polynomial_model(x_vals, *p),
            "label": f"poly degree {degree}",
        }

    if fit_type == "power":
        params = _safe_curve_fit(_power_model, x, y, p0=[1.0, 1.0], sigma=yerr)
        return {
            "type": "power",
            "params": params,
            "model": _power_model,
            "label": f"power fit: y = {params[0]:.3g} x^{params[1]:.3g}",
        }

    if fit_type == "power_offset":
        params = _safe_curve_fit(_power_offset_model, x, y, p0=[1.0, 1.0, 0.0], sigma=yerr)
        return {
            "type": "power_offset",
            "params": params,
            "model": _power_offset_model,
            "label": f"power+offset fit: y = {params[0]:.3g} x^{params[1]:.3g} + {params[2]:.3g}",
        }

    if fit_type == "shifted_power":
        params = _safe_curve_fit(_shifted_power_model, x, y, p0=[1.0, 1.0, np.min(x) * 0.1], sigma=yerr)
        return {
            "type": "shifted_power",
            "params": params,
            "model": _shifted_power_model,
            "label": f"shifted power fit",
        }

    if fit_type == "custom":
        custom_func = fit_spec.get("func")
        p0 = fit_spec.get("p0")
        if custom_func is None or not callable(custom_func):
            raise ValueError("custom fit requires a callable 'func' field.")
        params = _safe_curve_fit(custom_func, x, y, p0=p0, sigma=yerr)
        return {
            "type": "custom",
            "params": params,
            "model": custom_func,
            "label": f"custom fit ({custom_func.__name__})",
        }

    raise ValueError(f"Unsupported fit type: {fit_type}")


def make_graph(
    x,
    y,
    save=False,
    title=None,
    fit=None,
    filename=None,
    xlabel="x",
    ylabel="y",
    xerr=None,
    yerr=None,
    errorbar_kwargs=None,
    show=True,
    figsize=(8, 5),
):
    """Plot x vs y with an optional analytic fit.

    Parameters
    ----------
    x : array-like
        Input x data.
    y : array-like
        Input y data.
    save : bool, optional
        If True, save the figure to disk using `filename`.
    title : str, optional
        Plot title.
    fit : str, tuple, or dict, optional
        Fit specification. Supported forms:
        - "linear"
        - "quadratic"
        - "cubic"
        - ("poly", degree)
        - "power"
        - "power_offset"
        - "shifted_power"
        - {"type": "custom", "func": callable, "p0": initial_guess}
    filename : str, optional
        Output filename when saving. Default is "graph.png".
    xlabel : str, optional
        Label for the x-axis.
    ylabel : str, optional
        Label for the y-axis.
    xerr : array-like or scalar, optional
        Errorbar values for x.
    yerr : array-like or scalar, optional
        Errorbar values for y.
    errorbar_kwargs : dict, optional
        Additional keyword arguments passed to `matplotlib.axes.Axes.errorbar`.
    show : bool, optional
        Whether to display the figure.
    figsize : tuple, optional
        Figure size in inches.

    Returns
    -------
    tuple
        (fig, ax, fit_result) where fit_result is None when no fit was requested.
    """

    x = np.asarray(x)
    y = np.asarray(y)
    if x.shape != y.shape:
        raise ValueError("x and y must have the same shape.")

    fig, ax = plt.subplots(figsize=figsize)
    if xerr is None and yerr is None:
        ax.scatter(x, y, label="data", color="C0", alpha=0.8)
    else:
        plot_kwargs = {
            "fmt": "o",
            "label": "data",
            "color": "C0",
            "alpha": 0.8,
            "capsize": 3,
        }
        if errorbar_kwargs is not None:
            plot_kwargs.update(errorbar_kwargs)
        ax.errorbar(x, y, xerr=xerr, yerr=yerr, **plot_kwargs)

    fit_result = _generate_fit(x, y, fit, yerr=yerr)
    if fit_result is not None:
        x_line = np.linspace(np.nanmin(x), np.nanmax(x), 300)
        y_line = fit_result["model"](x_line, *fit_result["params"])
        ax.plot(x_line, y_line, label=fit_result["label"], color="C1")

    ax.set_title(title if title is not None else "Data plot")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.legend()

    if save:
        target_name = filename if filename else "graph.png"
        fig.savefig(target_name, dpi=150, bbox_inches="tight")

    if show:
        plt.show()

    return fig, ax, fit_result
