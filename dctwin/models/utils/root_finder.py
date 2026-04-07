from typing import Tuple

import torch


def solve_root(
    eps,  # required absolute accuracy
    max_ite,  # maximum number of allowed iterations
    flag,  # integer storing exit status
    x_res,  # value of x that solves f(x,Par) = 0
    f,  # function
    x_0,  # 1st bound of interval that contains the solution
    x_1,  # 2nd bound of interval that contains the solution
) -> Tuple[int, float | torch.Tensor]:
    """
    PURPOSE OF THIS SUBROUTINE:
        Find the value of x between x0 and x1 such that f(x,Par) is equal to zero.
    METHODOLOGY EMPLOYED:
        Uses the Regula Falsi (false position) method (similar to secant method) SUBROUTINE ARGUMENT DEFINITIONS:
            = -2: f(x0) and f(x1) have the same sign
            = -1: no convergence
            >  0: number of iterations performed
    """
    small = 1e-10
    x0 = x_0  # present 1st bound
    x1 = x_1  # present 2nd bound
    x_temp = x0  # new estimate
    n_ite = 0  # number of iterations
    alt_ite = 0  # a counter used for Alternation choice
    y0 = f(x0)  # f at X0
    y1 = f(x1)  # f at X1

    if y0 * y1 > 0:
        flag = -2
        x_res = x0
        return flag, x_res

    while True:
        dy = y0 - y1

        if abs(dy) < small:
            dy = small

        if abs(x1 - x0) < small:
            break

        x_temp = (y0 * x1 - y1 * x0) / dy
        y_temp = f(x_temp)

        n_ite += 1
        alt_ite += 1

        if abs(y_temp) < eps:
            flag = n_ite
            x_res = x_temp
            return flag, x_res

        # OK, so we didn't converge, lets check max iterations to see if we should break early
        if n_ite > max_ite:
            break

        # Finally, if we make it here, we haven't converged, and we still have iterations left, so continue
        # and reassign values (only if further iteration required)

        if y0 < 0.0:
            if y_temp < 0.0:
                x0 = x_temp
                y0 = y_temp
            else:
                x1 = x_temp
                y1 = y_temp
        else:
            if y_temp < 0.0:
                x1 = x_temp
                y1 = y_temp
            else:
                x0 = x_temp
                y0 = y_temp

    # if we make it here we haven't converged, so just set the flag and leave
    flag = -1
    x_res = x_temp
    return flag, x_res
