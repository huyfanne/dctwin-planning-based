FROM nvidia/cuda:12.4.1-devel-ubuntu22.04 AS builder1

# install basic dependencies
RUN apt-get update
RUN apt-get install -y git build-essential m4 flex zlib1g-dev wget python3

# install cmake v3.27
WORKDIR /root
RUN mkdir -p /opt/cmake
RUN wget https://github.com/Kitware/CMake/releases/download/v3.27.2/cmake-3.27.2-linux-x86_64.sh
RUN sh cmake-3.27.2-linux-x86_64.sh --skip-license --prefix=/opt/cmake
RUN echo 'export PATH=$PATH:/opt/cmake/bin' >> /etc/bash.bashrc

# install openmpi with CUDA support
WORKDIR /root
RUN mkdir -p /opt/openmpi-4.0.5
RUN wget https://download.open-mpi.org/release/open-mpi/v4.0/openmpi-4.0.5.tar.gz
RUN tar zxvf openmpi-4.0.5.tar.gz
RUN rm -f *.tar.gz
WORKDIR /root/openmpi-4.0.5
RUN ./configure --prefix=/opt/openmpi-4.0.5 --with-cuda=/usr/local/cuda
RUN make -j all
RUN make install
RUN echo 'export PATH=$PATH:/opt/openmpi-4.0.5/bin' >> /etc/bash.bashrc
RUN echo 'export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/openmpi-4.0.5/lib' >> /etc/bash.bashrc
ENV PATH $PATH:/opt/openmpi-4.0.5/bin
ENV LD_LIBRARY_PATH $LD_LIBRARY_PATH:/opt/openmpi-4.0.5/lib
ENV CPLUS_INCLUDE_PATH /opt/openmpi-4.0.5/include:$CPLUS_INCLUDE_PATH

# install AMGX
WORKDIR /root
RUN git clone --recursive https://github.com/nvidia/amgx.git
RUN mkdir -p amgx/build
RUN mkdir -p /opt/amgx
WORKDIR /root/amgx/build
RUN pwd
RUN /opt/cmake/bin/cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/amgx -DCUDA_ARCH="60;70;80;86" ..
RUN make -j all
RUN make install
RUN echo 'export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/amgx/lib' >> /etc/bash.bashrc

# Download OpenFOAM v2306
RUN mkdir -p /opt/OpenFOAM
WORKDIR /opt/OpenFOAM
RUN wget https://dl.openfoam.com/source/v2306/OpenFOAM-v2306.tgz
RUN wget https://dl.openfoam.com/source/v2306/ThirdParty-v2306.tgz
RUN tar zxf OpenFOAM-v2306.tgz
RUN tar zxf ThirdParty-v2306.tgz
RUN rm *.tgz

# complie OpenFOAM。
WORKDIR /opt/OpenFOAM/OpenFOAM-v2306
ENV CPLUS_INCLUDE_PATH /opt/openmpi-4.0.5/include:$CPLUS_INCLUDE_PATH
ENV CPPLUS_INCLUDE_PATH /opt/openmpi-4.0.5/include:$CPPLUS_INCLUDE_PATH
ENV LD_LIBRARY_PATH /opt/openmpi-4.0.5/lib:$LD_LIBRARY_PATH
ENV PATH /opt/openmpi-4.0.5/bin/:$PATH
RUN ["/bin/bash", "-c", "source /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc && ./Allwmake -j 8 -s -q -l -k"]
RUN echo 'source /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc' >> /etc/bash.bashrc

# install PETSc
WORKDIR /root
RUN git clone -b release https://gitlab.com/petsc/petsc.git
RUN mkdir -p /opt/petsc
WORKDIR /root/petsc
RUN ["/bin/bash", "-c", "source /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc && ./configure --prefix=$WM_THIRD_PARTY_DIR/platforms/$WM_ARCH$WM_COMPILER$WM_PRECISION_OPTION$WM_LABEL_OPTION/petsc-git PETSC_ARCH=$WM_OPTIONS --prefix=/opt/petsc --with-64-bit-indices=0 --with-precision=double --with-cuda=1 --with-cuda-arch=75 --gpu-architecture=sm_75 --with-openmpi=1 --with-openmpi-dir=/opt/openmpi-4.0.5/ --with-fc=0 --force --with-debugging=0 COPTFLAGS='-O3 -march=native -mtune=native' CXXOPTFLAGS='-O3 -march=native -mtune=native' FOPTFLAGS='-O3 -march=native -mtune=native' --download-f2cblaslapack=1 --download-hypre=1"]
RUN ["/bin/bash", "-c", "source /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc && make PETSC_DIR=. PETSC_ARCH=linux64GccDPInt32Opt -j all"]
RUN ["/bin/bash", "-c", "source /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc && make PETSC_DIR=. PETSC_ARCH=linux64GccDPInt32Opt install"]
RUN echo 'export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/petsc/lib' >> /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc

# # install foam2csr
WORKDIR /root
RUN git clone https://gitlab.hpc.cineca.it/openfoam/foam2csr.git
RUN echo 'export CUBROOT=/root/amgx/thrust/dependencies/' >> /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc
RUN echo 'export PETSC_INC=/opt/petsc/include' >> /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc
RUN echo 'export PETSC_LIB_DIR=/opt/petsc/lib' >> /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc
RUN echo 'export AMGX_INC=/opt/amgx/include' >> /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc
RUN echo 'export AMGX_LIB=/opt/amgx/lib' >> /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc
RUN echo 'export SPECTRUM_MPI_HOME=/opt/openmpi-4.0.5' >> /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc
WORKDIR /root/foam2csr
RUN sed -i 's/NVARCH = 70/NVARCH = 75/g' "/root/foam2csr/Make/nvcc"
RUN ["/bin/bash", "-c", "source /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc && ./Allwmake -j"]

# install PETSc4FOAM with AMGXWrapper support
WORKDIR /root
RUN git clone --branch amgxwrapper https://develop.openfoam.com/modules/external-solver.git petsc4foam
WORKDIR /root/petsc4foam
ENV CUBROOT /root/amgx/thrust/dependencies/
ENV FOAM2CSR_INC /root/foam2csr/src
ENV AMGX_INC /opt/amgx/include
ENV SPECTRUM_MPI_HOME /opt/openmpi-4.0.5
RUN echo $SPECTRUM_MPI_HOME
ENV PETSC_LIB_DIR /opt/petsc/lib
ENV AMGX_LIB /opt/amgx/lib
ENV CUDA_INC /usr/local/cuda/include
ENV PETSC_ARCH_PATH /opt/petsc
ENV PETSC_INC /opt/petsc/include
RUN sed -i 's/-I$(FOAM2CSR_INC)/-I$(FOAM2CSR_INC) -I$(CUDA_INC)/' src/petsc4Foam/Make/options
RUN ["/bin/bash", "-c", "source /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc && ./Allwclean && ./Allwmake -j"]

RUN env | grep -v 'no_proxy' > /env.list

WORKDIR /root

FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

COPY --from=builder1 /opt/openmpi-4.0.5 /opt/openmpi-4.0.5
COPY --from=builder1 /opt/amgx /opt/amgx
COPY --from=builder1 /opt/OpenFOAM/ThirdParty-v2306 /opt/OpenFOAM/ThirdParty-v2306
COPY --from=builder1 /opt/petsc /opt/petsc
COPY --from=builder1 /opt/OpenFOAM/OpenFOAM-v2306 /opt/OpenFOAM/OpenFOAM-v2306

COPY --from=builder1 /root/OpenFOAM/user-v2306 /root/OpenFOAM/user-v2306
COPY --from=builder1 /root/amgx /root/amgx


# Install ssh
RUN apt-get update
RUN apt-get install -y openssh-client

ENV CPLUS_INCLUDE_PATH /opt/openmpi-4.0.5/include:$CPLUS_INCLUDE_PATH
ENV CPPLUS_INCLUDE_PATH /opt/openmpi-4.0.5/include:$CPPLUS_INCLUDE_PATH
RUN echo 'export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/petsc/lib' >> /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc
RUN echo 'export CUBROOT=/root/amgx/thrust/dependencies/' >> /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc
RUN echo 'export PETSC_INC=/opt/petsc/include' >> /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc
RUN echo 'export PETSC_LIB_DIR=/opt/petsc/lib' >> /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc
RUN echo 'export AMGX_INC=/opt/amgx/include' >> /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc
RUN echo 'export AMGX_LIB=/opt/amgx/lib' >> /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc
RUN echo 'export SPECTRUM_MPI_HOME=/opt/openmpi-4.0.5' >> /opt/OpenFOAM/OpenFOAM-v2306/etc/bashrc
ENV LD_LIBRARY_PATH $LD_LIBRARY_PATH:/root/OpenFOAM/user-v2306/platforms/linux64GccDPInt32Opt/lib
ENV LD_LIBRARY_PATH $LD_LIBRARY_PATH:/opt/OpenFOAM/OpenFOAM-v2306/site/2306/platforms/linux64GccDPInt32Opt/lib
ENV LD_LIBRARY_PATH $LD_LIBRARY_PATH:/opt/OpenFOAM/OpenFOAM-v2306/platforms/linux64GccDPInt32Opt/lib/sys-openmpi
ENV LD_LIBRARY_PATH $LD_LIBRARY_PATH:/opt/OpenFOAM/OpenFOAM-v2306/platforms/linux64GccDPInt32Opt/lib
ENV LD_LIBRARY_PATH $LD_LIBRARY_PATH:/opt/OpenFOAM/ThirdParty-v2306/platforms/linux64GccDPInt32/lib/sys-openmpi
ENV LD_LIBRARY_PATH $LD_LIBRARY_PATH:/opt/OpenFOAM/ThirdParty-v2306/platforms/linux64GccDPInt32/lib
ENV LD_LIBRARY_PATH $LD_LIBRARY_PATH:/opt/OpenFOAM/ThirdParty-v2306/platforms/linux64Gcc/fftw-3.3.10/lib
ENV LD_LIBRARY_PATH $LD_LIBRARY_PATH:/opt/OpenFOAM/ThirdParty-v2306/platforms/linux64Gcc/CGAL-4.14.3/lib64
ENV LD_LIBRARY_PATH $LD_LIBRARY_PATH:/opt/OpenFOAM/ThirdParty-v2306/platforms/linux64Gcc/boost_1_74_0/lib64
ENV LD_LIBRARY_PATH $LD_LIBRARY_PATH:/opt/openmpi-4.0.5/lib
ENV LD_LIBRARY_PATH $LD_LIBRARY_PATH:/opt/OpenFOAM/OpenFOAM-v2306/platforms/linux64GccDPInt32Opt/lib/dummy
ENV LD_LIBRARY_PATH $LD_LIBRARY_PATH:/opt/amgx/lib
ENV LD_LIBRARY_PATH $LD_LIBRARY_PATH:/opt/petsc/lib

ENV PATH $PATH:/root/OpenFOAM/user-v2306/platforms/linux64GccDPInt32Opt/bin
ENV PATH $PATH:/opt/OpenFOAM/OpenFOAM-v2306/site/2306/platforms/linux64GccDPInt32Opt/bin
ENV PATH $PATH:/opt/OpenFOAM/OpenFOAM-v2306/platforms/linux64GccDPInt32Opt/bin
ENV PATH $PATH:/opt/OpenFOAM/OpenFOAM-v2306/bin
ENV PATH $PATH:/opt/OpenFOAM/OpenFOAM-v2306/wmake
ENV PATH $PATH:/opt/openmpi-4.0.5/bin/
ENV PATH $PATH:/opt/openmpi-4.0.5/bin
ENV PATH $PATH:/opt/cmake/bin



ENV CUBROOT /root/amgx/thrust/dependencies/
ENV FOAM2CSR_INC /root/foam2csr/src
ENV AMGX_INC /opt/amgx/include
ENV SPECTRUM_MPI_HOME /opt/openmpi-4.0.5
RUN echo $SPECTRUM_MPI_HOME
ENV PETSC_LIB_DIR /opt/petsc/lib
ENV AMGX_LIB /opt/amgx/lib
ENV CUDA_INC /usr/local/cuda/include
ENV PETSC_ARCH_PATH /opt/petsc
ENV PETSC_INC /opt/petsc/include
ENV CGAL_ARCH_PATH /opt/OpenFOAM/ThirdParty-v2306/platforms/linux64Gcc/CGAL-4.14.3
ENV FOAM_MPI sys-openmpi
ENV WM_PRECISION_OPTION DP
ENV WM_PROJECT_USER_DIR /root/OpenFOAM/user-v2306
ENV WM_MPLIB SYSTEMOPENMPI
ENV FOAM_RUN /root/OpenFOAM/user-v2306/run
ENV FOAM_EXT_LIBBIN /opt/OpenFOAM/ThirdParty-v2306/platforms/linux64GccDPInt32/lib
ENV WM_OPTIONS linux64GccDPInt32Opt
ENV FFTW_ARCH_PATH /opt/OpenFOAM/ThirdParty-v2306/platforms/linux64Gcc/fftw-3.3.10
ENV SPECTRUM_MPI_HOME /opt/openmpi-4.0.5
ENV WM_LABEL_SIZE 32
ENV WM_PROJECT OpenFOAM
ENV FOAM_APPBIN /opt/OpenFOAM/OpenFOAM-v2306/platforms/linux64GccDPInt32Opt/bin
ENV WM_THIRD_PARTY_DIR /opt/OpenFOAM/ThirdParty-v2306
ENV WM_LABEL_OPTION Int32
ENV FOAM_LIBBIN /opt/OpenFOAM/OpenFOAM-v2306/platforms/linux64GccDPInt32Opt/lib
ENV FOAM_ETC /opt/OpenFOAM/OpenFOAM-v2306/etc
ENV FOAM_UTILITIES /opt/OpenFOAM/OpenFOAM-v2306/applications/utilities
ENV FOAM_SITE_LIBBIN /opt/OpenFOAM/OpenFOAM-v2306/site/2306/platforms/linux64GccDPInt32Opt/lib
ENV AMGX_LIB /opt/amgx/lib
ENV CPLUS_INCLUDE_PATH /opt/openmpi-4.0.5/include:/opt/openmpi-4.0.5/include:
ENV ADIOS2_ARCH_PATH /opt/OpenFOAM/ThirdParty-v2306/platforms/linux64Gcc/ADIOS2-2.8.3
ENV FOAM_SITE_APPBIN /opt/OpenFOAM/OpenFOAM-v2306/site/2306/platforms/linux64GccDPInt32Opt/bin
ENV MPI_ARCH_PATH /opt/openmpi-4.0.5
ENV LIBRARY_PATH /usr/local/cuda/lib64/stubs
ENV FOAM_SRC /opt/OpenFOAM/OpenFOAM-v2306/src
ENV SCOTCH_ARCH_PATH /opt/OpenFOAM/ThirdParty-v2306/platforms/linux64GccDPInt32/scotch_6.1.0
ENV BOOST_ARCH_PATH /opt/OpenFOAM/ThirdParty-v2306/platforms/linux64Gcc/boost_1_74_0
ENV PETSC_LIB_DIR /opt/petsc/lib
ENV FOAM_USER_LIBBIN /root/OpenFOAM/user-v2306/platforms/linux64GccDPInt32Opt/lib
ENV FOAM_APP /opt/OpenFOAM/OpenFOAM-v2306/applications
ENV FOAM2CSR_INC /root/foam2csr/src
ENV FOAM_API 2306
ENV WM_COMPILE_OPTION Opt
ENV PETSC_INC /opt/petsc/include
ENV FOAM_SOLVERS /opt/OpenFOAM/OpenFOAM-v2306/applications/solvers
ENV WM_PROJECT_DIR /opt/OpenFOAM/OpenFOAM-v2306
ENV WM_COMPILER_TYPE system
ENV FOAM_USER_APPBIN /root/OpenFOAM/user-v2306/platforms/linux64GccDPInt32Opt/bin
ENV WM_COMPILER_LIB_ARCH 64
ENV PETSC_ARCH_PATH /opt/petsc

ENV WM_COMPILER Gcc
ENV NV_NVML_DEV_VERSION 12.4.127-1
ENV NV_LIBNCCL_DEV_PACKAGE libnccl-dev=2.21.5-1+cuda12.4
ENV NV_LIBNCCL_DEV_PACKAGE_VERSION 2.21.5-1
ENV NV_LIBCUBLAS_DEV_PACKAGE libcublas-dev-12-4=12.4.5.8-1
ENV NV_CUDA_CUDART_DEV_VERSION 12.4.127-1
ENV NV_NVPROF_DEV_PACKAGE cuda-nvprof-12-4=12.4.127-1
ENV WM_ARCH linux64
ENV NV_LIBNCCL_DEV_PACKAGE_NAME libnccl-dev
ENV FOAM_TUTORIALS /opt/OpenFOAM/OpenFOAM-v2306/tutorials
ENV NV_LIBCUBLAS_DEV_VERSION 12.4.5.8-1
ENV NV_LIBCUBLAS_DEV_PACKAGE_NAME libcublas-dev-12-4
ENV NV_CUDA_NSIGHT_COMPUTE_DEV_PACKAGE cuda-nsight-compute-12-4=12.4.1-1
ENV NV_LIBNPP_DEV_PACKAGE libnpp-dev-12-4=12.2.5.30-1
ENV NV_LIBNPP_DEV_VERSION 12.2.5.30-1
ENV WM_PROJECT_VERSION v2306
ENV WM_DIR /opt/OpenFOAM/OpenFOAM-v2306/wmake
ENV NV_LIBCUSPARSE_DEV_VERSION 12.3.1.170-1
ENV NV_CUDA_NSIGHT_COMPUTE_VERSION 12.4.1-1
ENV PETSC_INC /opt/petsc/include
ENV NV_NVPROF_VERSION 12.4.127-1

WORKDIR /root