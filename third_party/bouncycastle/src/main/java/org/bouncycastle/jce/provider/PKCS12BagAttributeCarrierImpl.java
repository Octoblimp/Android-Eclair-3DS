package org.bouncycastle.jce.provider;

import org.bouncycastle.jce.interfaces.PKCS12BagAttributeCarrier;
// BEGIN android-added
import org.bouncycastle.asn1.OrderedTable;
// END android-added
import org.bouncycastle.asn1.DERObjectIdentifier;
import org.bouncycastle.asn1.DEREncodable;
import org.bouncycastle.asn1.ASN1OutputStream;
import org.bouncycastle.asn1.ASN1InputStream;

import java.util.Enumeration;
import java.util.Hashtable;
import java.util.Vector;
import java.io.ObjectOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.ObjectInputStream;

class PKCS12BagAttributeCarrierImpl
    implements PKCS12BagAttributeCarrier
{
    // BEGIN android-changed
    private OrderedTable pkcs12 = new OrderedTable();
    // END android-changed

    // BEGIN android-removed
    // PKCS12BagAttributeCarrierImpl(Hashtable attributes, Vector ordering)
    // {
    //     this.pkcs12Attributes = attributes;
    //     this.pkcs12Ordering = ordering;
    // }
    // END android-removed

    public PKCS12BagAttributeCarrierImpl()
    {
        // BEGIN android-removed
        // this(new Hashtable(), new Vector());
        // END android-removed
    }

    public void setBagAttribute(
        DERObjectIdentifier oid,
        DEREncodable        attribute)
    {
        // BEGIN android-changed
        // preserve original ordering
        pkcs12.put(oid, attribute);
        // END android-changed
    }

    public DEREncodable getBagAttribute(
        DERObjectIdentifier oid)
    {
        // BEGIN android-changed
        return (DEREncodable)pkcs12.get(oid);
        // END android-changed
    }

    public Enumeration getBagAttributeKeys()
    {
        // BEGIN android-changed
        return pkcs12.getKeys();
        // END android-changed
    }

    int size()
    {
        // BEGIN android-changed
        return pkcs12.size();
        // END android-changed
    }

    // BEGIN android-removed
    // Hashtable getAttributes()
    // {
    //     return pkcs12Attributes;
    // }
    //
    // Vector getOrdering()
    // {
    //     return pkcs12Ordering;
    // }
    // END android-removed

    public void writeObject(ObjectOutputStream out)
        throws IOException
    {
        if (pkcs12.size() == 0)
        {
            out.writeObject(new Hashtable());
            out.writeObject(new Vector());
        }
        else
        {
            ByteArrayOutputStream bOut = new ByteArrayOutputStream();
            ASN1OutputStream aOut = new ASN1OutputStream(bOut);

            Enumeration             e = this.getBagAttributeKeys();

            while (e.hasMoreElements())
            {
                DERObjectIdentifier    oid = (DERObjectIdentifier)e.nextElement();

                aOut.writeObject(oid);
                aOut.writeObject(pkcs12.get(oid));
            }

            out.writeObject(bOut.toByteArray());
        }
    }

    public void readObject(ObjectInputStream in)
        throws IOException, ClassNotFoundException
    {
        Object obj = in.readObject();

        if (obj instanceof Hashtable)
        {
            // BEGIN android-changed
            // we only write out Hashtable/Vector in empty case
            in.readObject(); // consume empty Vector
            this.pkcs12 = new OrderedTable();
            // END android-changed
        }
        else
        {
            ASN1InputStream aIn = new ASN1InputStream((byte[])obj);

            DERObjectIdentifier    oid;

            while ((oid = (DERObjectIdentifier)aIn.readObject()) != null)
            {
                this.setBagAttribute(oid, aIn.readObject());
            }
        }
    }
}
