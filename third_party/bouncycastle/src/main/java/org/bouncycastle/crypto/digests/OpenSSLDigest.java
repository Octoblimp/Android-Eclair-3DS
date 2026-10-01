/*
 * Copyright (C) 2008 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package org.bouncycastle.crypto.digests;

import org.apache.harmony.xnet.provider.jsse.NativeCrypto;
import org.bouncycastle.crypto.ExtendedDigest;

/**
 * Implements the BouncyCastle Digest interface using OpenSSL's EVP API.
 */
public class OpenSSLDigest implements ExtendedDigest {

    /**
     * Holds the standard name of the hashing algorithm, e.g. "SHA-1";
     */
    private final String algorithm;

    /**
     * Holds the OpenSSL name of the hashing algorithm, e.g. "sha1";
     */
    private final String openssl;

    /**
     * Holds a pointer to the native message digest context.
     */
    private int ctx;

    /**
     * Holds a dummy buffer for writing single bytes to the digest.
     */
    private final byte[] singleByte = new byte[1];

    /**
     * Creates a new OpenSSLMessageDigest instance for the given algorithm
     * name.
     *
     * @param algorithm The standard name of the algorithm, e.g. "SHA-1".
     * @param algorithm The name of the openssl algorithm, e.g. "sha1".
     */
    private OpenSSLDigest(String algorithm, String openssl) {
        this.algorithm = algorithm;
        this.openssl = openssl;
        ctx = NativeCrypto.EVP_MD_CTX_create();
        try {
            NativeCrypto.EVP_DigestInit(ctx, openssl);
        } catch (Exception ex) {
            throw new RuntimeException(ex.getMessage() + " (" + algorithm + ")");
        }
    }

    public int doFinal(byte[] out, int outOff) {
        int i = NativeCrypto.EVP_DigestFinal(ctx, out, outOff);
        reset();
        return i;
    }

    public String getAlgorithmName() {
        return algorithm;
    }

    public int getDigestSize() {
        return NativeCrypto.EVP_MD_CTX_size(ctx);
    }

    public int getByteLength() {
        return NativeCrypto.EVP_MD_CTX_block_size(ctx);
    }

    public void reset() {
        NativeCrypto.EVP_DigestInit(ctx, openssl);
    }

    public void update(byte in) {
        singleByte[0] = in;
        NativeCrypto.EVP_DigestUpdate(ctx, singleByte, 0, 1);
    }

    public void update(byte[] in, int inOff, int len) {
        NativeCrypto.EVP_DigestUpdate(ctx, in, inOff, len);
    }

    @Override
    protected void finalize() throws Throwable {
        super.finalize();
        NativeCrypto.EVP_MD_CTX_destroy(ctx);
        ctx = 0;
    }

    public static class MD5 extends OpenSSLDigest {
        public MD5() { super("MD5", "md5"); }
    }

    public static class SHA1 extends OpenSSLDigest {
        public SHA1() { super("SHA-1", "sha1"); }
    }

    public static class SHA256 extends OpenSSLDigest {
        public SHA256() { super("SHA-256", "sha256"); }
    }

    public static class SHA384 extends OpenSSLDigest {
        public SHA384() { super("SHA-384", "sha384"); }
    }

    public static class SHA512 extends OpenSSLDigest {
        public SHA512() { super("SHA-512", "sha512"); }
    }
}
